from django.db import transaction
from django.utils import timezone
from items import models
from .notification_service import NotificationService

class ClaimService:
    """
    Business logic layer for Claim life-cycle management.
    """

    @classmethod
    @transaction.atomic
    def submit_claim(cls, claimer, item, form):
        """
        Creates a new claim and notifies relevant parties.
        """
        claim = form.save(commit=False)
        claim.item = item
        claim.claimer = claimer
        claim.save()

        # 1. Notify Owner & Admins
        if item.owner:
            NotificationService.send_status_notification(item.owner, item, 'claim_submitted')
            
            # Create a System Message (DM) for the owner
            models.DirectMessage.objects.create(
                sender=claimer, 
                recipient=item.owner, 
                item=item,
                is_system=True,
                content=f"SYSTEM: User @{claimer.username} has submitted a claim for '{item.name}'.\n\nMESSAGE: {claim.message}"
            )

        NotificationService.notify_admins(item, 'claim_submitted')
        
        # 2. Money Match Quality Scoring
        if item.is_money:
            cls._calculate_money_match_quality(claim, item)
            
        # 3. Notify Claimer
        NotificationService.send_status_notification(claimer, item, 'claim_confirmation')
            
        return claim

    @classmethod
    def _calculate_money_match_quality(cls, claim, item):
        """
        Internal logic to assess how closely the claim matches the found item.
        Scores are used for administrative prioritization (not shown to users).
        """
        if not claim.claimed_amount:
            return 0
            
        score = 0
        try:
            reported_amount = float(item.amount or 0)
            claimed_amount = float(claim.claimed_amount or 0)
        except (ValueError, TypeError):
            return 0
        
        # 1. Amount Proximity (Up to 60 points)
        if reported_amount > 0:
            diff_percent = abs(reported_amount - claimed_amount) / reported_amount
            if diff_percent == 0: score += 60
            elif diff_percent <= 0.05: score += 50
            elif diff_percent <= 0.15: score += 30
        
        # 2. Denomination Matching (Up to 40 points)
        # Low-fidelity check: keyword overlap
        claimed_denoms = (claim.claimed_denominations or "").lower().replace('$',' ').replace('x',' ')
        source_denoms = (item.denominations or "").lower().replace('$',' ').replace('x',' ')
        
        claimed_tokens = set(claimed_denoms.split())
        source_tokens = set(source_denoms.split())
        
        common = claimed_tokens & source_tokens
        if common:
            score += min(len(common) * 10, 40)
            
        # Log score in admin remarks for now
        claim.admin_remarks = f"System Match Quality Score: {score}/100"
        claim.save()
        return score

    @classmethod
    @transaction.atomic
    def approve_claim(cls, claim, authorizer, remarks=""):
        """
        Approves a claim, marking the item as 'CLAIMED' (Pending Claim), 
        and rejects competing claims.
        """
        item = claim.item
        
        # 1. Update Claim with Handover Security
        import uuid
        claim.status = 'approved'
        claim.admin_remarks = remarks
        claim.verification_token = uuid.uuid4()
        claim.save()

        # 2. Update Item Lifecycle: Move to CLAIMED (Removes from public feed)
        item.lifecycle_status = 'claimed'
        item.date_resolved = timezone.now()
        item.save()

        # 3. Reject other pending claims and notify them
        competing_claims = models.ClaimRequest.objects.filter(
            item=item, 
            status='pending'
        ).exclude(id=claim.id)
        
        for rejected_claim in competing_claims:
            NotificationService.send_status_notification(
                rejected_claim.claimer, item, 'claim_auto_rejected'
            )
        competing_claims.update(status='rejected')

        # 4. Notify & Audit
        NotificationService.send_status_notification(claim.claimer, item, 'claim_approved')
        
        models.AuditLog.objects.create(
            user=authorizer, action="Approved Claim", item=item,
            details=f"Claim approved. Item '{item.name}' moved to CLAIMED stage."
        )

        return claim

    @classmethod
    @transaction.atomic
    def reject_claim(cls, claim, authorizer, remarks="Proof insufficient."):
        """Denies a claim request. Item remains ACTIVE."""
        claim.status = 'rejected'
        claim.admin_remarks = remarks
        claim.save()

        # No change to item.lifecycle_status (stays 'active' or 'claimed' if other claims exist)
        # Note: If this was the last approved claim, we might want to revert to ACTIVE, 
        # but usually we handle multiple claims by keeping it ACTIVE until one is APPROVED.

        NotificationService.send_status_notification(claim.claimer, claim.item, 'claim_rejected')
        
    @classmethod
    @transaction.atomic
    def complete_claim(cls, claim, authorizer):
        """Finalizes the turnover. Item moves to RESOLVED."""
        claim.status = 'completed'
        claim.save()

        item = claim.item
        item.lifecycle_status = 'resolved'
        item.date_resolved = item.date_resolved or timezone.now()
        item.save()

        # Notify claimer that turnover is complete
        NotificationService.send_status_notification(claim.claimer, item, 'claim_completed')
        
        # Notify item owner that their item has been returned
        if item.owner and item.owner != claim.claimer:
            NotificationService.send_status_notification(item.owner, item, 'item_resolved')

        models.AuditLog.objects.create(
            user=authorizer, action="Completed Claim", item=item,
            details=f"Item '{item.name}' turnover completed to @{claim.claimer.username} by Admin @{authorizer.username}."
        )

        # Cross-resolve any linked matches so both pair items are removed from registry
        from django.db.models import Q
        linked_matches = models.MatchSuggestion.objects.filter(
            Q(lost_item=item) | Q(found_item=item),
            status='linked'
        )
        for match in linked_matches:
            matched_item = match.found_item if match.lost_item == item else match.lost_item
            if matched_item.lifecycle_status != 'resolved':
                matched_item.lifecycle_status = 'resolved'
                matched_item.date_resolved = timezone.now()
                matched_item.save()
                
                # Notify the matched item owner automatically
                if matched_item.owner:
                    NotificationService.send_status_notification(
                        matched_item.owner, matched_item, 'item_resolved'
                    )
                
                models.AuditLog.objects.create(
                    user=authorizer, action="Matched Item Auto-Resolved", item=matched_item,
                    details=f"Item '{matched_item.name}' automatically resolved because its linked match '{item.name}' was turned over."
                )
