import threading
import logging
from django.db import transaction
from django.contrib.auth.models import User
from items import models, ai_service
from .notification_service import NotificationService

logger = logging.getLogger(__name__)

class ItemService:
    """
    Business logic layer for Item lifecycle management.
    Ensures state transitions and side effects (notifications, matches) 
    are handled consistently.
    """

    @staticmethod
    def _find_potential_matches(item):
        """
        Upgraded AI-driven matching logic. 
        Uses Keyword intersection + Jaccard similarity of AI visual tags.
        """
        opposite_type = 'found' if item.report_type == 'lost' else 'lost'
        potential_candidates = models.Item.objects.filter(
            report_type=opposite_type,
            lifecycle_status='active',
            verification_status='approved'
        ).exclude(id=item.id)
        
        matches_found = []
        name_words = set(item.name.lower().split())
        item_ai_tags = set(tag.strip().lower() for tag in item.ai_tags.split(',') if tag.strip())

        for candidate in potential_candidates:
            score = 0.0
            
            # 1. Category check (Hard requirement)
            if candidate.category != item.category:
                continue
                
            # 2. Textual Similarity (Name & Description)
            candidate_name_words = set(candidate.name.lower().split())
            intersection = name_words & candidate_name_words
            
            # Semantic bonus: if name is found in description
            text_overlap = (item.name.lower() in candidate.description.lower()) or \
                           (candidate.name.lower() in item.description.lower())
            
            if intersection or text_overlap:
                # Base score for text match (0.4 if perfectly matched)
                text_score = (len(intersection) / max(len(name_words), 1))
                if text_overlap: text_score = max(text_score, 0.5)
                score += 0.4 * text_score
            
            # 3. AI visual similarity (If tags exist)
            candidate_ai_tags = set(tag.strip().lower() for tag in candidate.ai_tags.split(',') if tag.strip())
            if item_ai_tags and candidate_ai_tags:
                tag_intersection = item_ai_tags & candidate_ai_tags
                tag_union = item_ai_tags | candidate_ai_tags
                jaccard_score = len(tag_intersection) / len(tag_union)
                score += 0.6 * jaccard_score # AI has 60% weight if available
            else:
                # If no AI tags, scale the text score to be the primary indicator
                # This ensures matches still appear even if Vision API is down.
                score = score * 2.5 # Project 0.4 text score to 1.0 range
            
            # 4. Persistence & Threshold
            if score >= 0.35: # Slightly lower threshold for fallbacks
                # Create or update MatchSuggestion
                lost = item if item.report_type == 'lost' else candidate
                found = item if item.report_type == 'found' else candidate
                
                match_obj, created = models.MatchSuggestion.objects.update_or_create(
                    lost_item=lost,
                    found_item=found,
                    defaults={'score': min(round(score, 2), 1.0), 'status': 'pending'}
                )
                matches_found.append(match_obj)
                
        return matches_found

    @classmethod
    @transaction.atomic
    def report_item(cls, user, form):
        """
        Orchestrates item creation with decoupled state dimensions.
        Verification State: PENDING (student) or APPROVED (admin)
        Lifecycle State: ACTIVE (visible) or DRAFT (policy failure)
        """
        item = form.save(commit=False)
        item.owner = user
        
        # Determine Report Type from the 'status' field if it was passed, 
        # or it should be fixed if we updated the form. 
        if hasattr(item, 'status') and not item.report_type:
             item.report_type = item.status 
        
        # Backward compatibility sync: ensure 'status' field is also populated
        if item.report_type and not item.status:
             item.status = item.report_type

        logger.info(f"STARTING VALIDATION FOR ITEM NOMINEE: {item.name}")
        # Stage 2: Automated Validation & Filtering
        is_valid, reason = cls._validate_content(item)
        if not is_valid:
            # Policy Failure: Force to Rejected/Archived
            item.verification_status = 'rejected'
            item.lifecycle_status = 'archived'
            item.is_deleted = True
            item.save()
            
            models.AuditLog.objects.create(
                user=user, action="Auto-Rejected", item=item,
                details=f"Item auto-rejected during submission. Reason: {reason}"
            )
            return item, False, reason

        # Stage 3: Professional State Assignment
        is_admin = getattr(user, 'is_staff', False) or (user.userprofile.is_admin if hasattr(user, 'userprofile') else False)

        if is_admin:
            item.verification_status = 'approved'
            item.lifecycle_status = 'active'
            item.is_manually_verified = True
            # For admin reports, skip turnover if not needed, or keep pending if physical
            if item.is_money:
                item.turnover_status = 'confirmed'
        else:
            # Enforce Strict Admin Triage: All student/user reports must be reviewed
            item.verification_status = 'pending'
            item.lifecycle_status = 'draft'
            item.is_manually_verified = False
            
            # Money Turnover Requirement
            if item.is_money and item.report_type == 'found':
                item.turnover_status = 'pending'
            
        logger.info(f"FINALIZING ITEM STATE: Verification={item.verification_status}, Lifecycle={item.lifecycle_status}")
        item.save()

        # 1. Trigger Initial Notifications
        try:
            trigger = 'item_reported'
            NotificationService.send_status_notification(user, item, trigger)
            
            # 2. Match Detection (Only for non-rejected items)
            matches = cls._find_potential_matches(item)
            # Notification trigger for matches is now moved to the Match Dashboard (Admin Review First policy)

            # 3. Notify Admins
            if not is_admin:
                 NotificationService.notify_admins(item, trigger='admin_alert_new_report')
        except Exception as e:
            logger.error(f"NON-BLOCKING NOTIFICATION FAILURE: {e}", exc_info=True)

        # 4. Audit Trail
        models.AuditLog.objects.create(
            user=user, action="Accepted (Registry Staff)" if is_admin else "Submitted Report", 
            item=item,
            details=f"New {item.report_type} report submitted. Lifecycle: {item.lifecycle_status}, Verification: {item.verification_status}."
        )

        # 5. Background AI Processing
        if item.image:
            logger.info(f"INITIATING BACKGROUND TAGGING FOR ITEM {item.id}")
            cls._trigger_ai_tagging(item)

        logger.info(f"REPORT_ITEM COMPLETE FOR ID {item.id} - RETURNING SUCCESS")
        return item, True, None

    @classmethod
    @transaction.atomic
    def approve_item(cls, item, admin_user):
        """
        Approves a pending report and marks it as Active.
        """
        if item.verification_status == 'approved':
            return

        item.verification_status = 'approved'
        item.lifecycle_status = 'active'
        # Crucial: Approving a student report makes it live, but it does NOT 
        # make it an "Admin Report". The badge is reserved for admin-created entries.
        item.save()

        # Log action
        models.AuditLog.objects.create(
            user=admin_user, action="Approved Item", item=item,
            details=f"Item '{item.name}' approved and marked ACTIVE."
        )

        # Notify Owner
        if item.owner:
            NotificationService.send_status_notification(item.owner, item, 'item_approved')

        # Re-trigger match detection (persists suggestions for Admin review)
        cls._find_potential_matches(item)

    @classmethod
    @transaction.atomic
    def reject_item(cls, item, admin_user, reason="Policy violation"):
        """
        Explicitly rejects an item and moves it to ARCHIVED state.
        """
        item.verification_status = 'rejected'
        item.lifecycle_status = 'archived'
        item.save()
        
        item.soft_delete()

        models.AuditLog.objects.create(
            user=admin_user, action="Rejected Item", item=item,
            details=f"Item '{item.name}' rejected. Lifecycle moved to ARCHIVED. Reason: {reason}"
        )

        if item.owner:
            NotificationService.send_status_notification(item.owner, item, 'item_rejected', rejection_reason=reason)

    @classmethod
    @transaction.atomic
    def soft_delete_item(cls, item, user):
        """Handles the soft-deletion of an item with audit logging."""
        item.soft_delete()
        models.AuditLog.objects.create(
            user=user, action="Deleted Item", item=item,
            details=f"Item '{item.name}' soft-deleted."
        )

    @classmethod
    @transaction.atomic
    def revert_item(cls, item, admin_user):
        """
        Reverts an approved or rejected item back to pending queue.
        Used by the 5s Undo Buffer in the Admin Triage Console.
        """
        if item.verification_status == 'pending':
            return
            
        previous_status = item.verification_status
        item.verification_status = 'pending'
        item.lifecycle_status = 'active'
        item.is_deleted = False
        item.deleted_at = None
        item.save()

        models.AuditLog.objects.create(
            user=admin_user, action="Reverted Item Workflow", item=item,
            details=f"Item '{item.name}' reverted from '{previous_status}' back to pending."
        )

    @staticmethod
    def _trigger_ai_tagging(item):
        """Dispatches AI processing to a background thread."""
        def process():
            try:
                tags = ai_service.extract_image_tags(item.image.path)
                if tags:
                    # Update without full model save to avoid recursion or lock contention
                    models.Item.all_objects.filter(id=item.id).update(ai_tags=tags)
                    
                    # Race Condition Fix: If the item was immediately approved (Admin report),
                    # the pre-thread matcher failed because tags were empty. Re-run it now.
                    item.refresh_from_db()
                    if item.verification_status == 'approved' and item.lifecycle_status == 'active':
                        # Re-run Match Detection with populated tags
                        ItemService._find_potential_matches(item)
            except Exception as e:
                logger.error(f"AI Service Error during background tag for item {item.id}: {e}", exc_info=True)

        threading.Thread(target=process).start()

    @staticmethod
    def _validate_content(item):
        """
        Policy-based content validation for campus safety and system integrity.
        Returns (is_valid: bool, reason: str)
        """
        # 1. Prohibited Keywords Policy
        prohibited = ['drug', 'narcotic', 'weapon', 'firearm', 'explosive', 'illegal']
        full_text = f"{item.name} {item.description}".lower()
        
        for word in prohibited:
            if word in full_text:
                return False, f"Content contains prohibited terminology: '{word}'."

        # 2. Quality check
        is_money = item.category == 'Wallet / Money'
        min_name = 2 if is_money else 3
        min_desc = 3 if is_money else 5
        
        if len(item.name.strip()) < min_name:
            return False, f"Item name is too short. Please provide at least {min_name} characters."
            
        if len(item.description.strip()) < min_desc:
            return False, f"Description is too brief. Please provide at least {min_desc} characters to aid in matching."

        return True, None
