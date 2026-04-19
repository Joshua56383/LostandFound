import threading
import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.models import User
from items import models, ai_service

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Centralized service for handling all system-wide notifications.
    Implements a strict, categorization-based flow as per production standards.
    """

    # Trigger Configuration Map (Title, Category, Priority, Static Message Template)
    TRIGGER_CONFIG = {
        'item_reported': {
            'title': 'Report Submitted',
            'category': 'system',
            'priority': 'normal',
            'template': "We've received your report for '{item_name}'. It's now under review."
        },
        'item_approved': {
            'title': 'Good News!',
            'category': 'system',
            'priority': 'normal',
            'template': "Your report for '{item_name}' has been approved and is now live on the site."
        },
        'item_rejected': {
            'title': 'Quick Update',
            'category': 'system',
            'priority': 'normal',
            'template': "Your report for '{item_name}' couldn't be approved. Reason: {reason}"
        },
        'item_edited': {
            'title': 'Report Updated',
            'category': 'system',
            'priority': 'normal',
            'template': "Your report for '{item_name}' was approved with minor edits."
        },
        'item_deleted': {
            'title': 'Report Removed',
            'category': 'system',
            'priority': 'normal',
            'template': "Your report for '{item_name}' has been removed by an administrator."
        },
        'item_restored': {
            'title': 'Report Restored',
            'category': 'system',
            'priority': 'normal',
            'template': "Good news! Your report for '{item_name}' has been restored and is active again."
        },
        'claim_submitted': {
            'title': 'New Claim Request',
            'category': 'activity',
            'priority': 'high',
            'template': "Someone is looking to claim your item: '{item_name}'."
        },
        'claim_confirmation': {
            'title': 'Claim Received',
            'category': 'system',
            'priority': 'normal',
            'template': "Your claim for '{item_name}' has been received and is now under review."
        },
        'claim_approved': {
            'title': 'Claim Approved!',
            'category': 'activity',
            'priority': 'high',
            'template': "Great news! Your claim for '{item_name}' has been approved. Please wait for the admin to complete the turnover."
        },
        'claim_rejected': {
            'title': 'Claim Update',
            'category': 'activity',
            'priority': 'normal',
            'template': "Unfortunately, your claim for '{item_name}' was not approved. Reason: {reason}"
        },
        'claim_completed': {
            'title': 'Turnover Complete!',
            'category': 'system',
            'priority': 'high',
            'template': "The turnover for '{item_name}' is now complete. Thank you for using the Recovery Hub!"
        },
        'claim_auto_rejected': {
            'title': 'Claim Closed',
            'category': 'activity',
            'priority': 'normal',
            'template': "Your claim for '{item_name}' has been closed because another claim was approved."
        },
        'message_received': {
            'title': 'New Message',
            'category': 'activity',
            'priority': 'normal',
            'template': "You have a new message regarding '{item_name}'."
        },
        'item_resolved': {
            'title': 'Item Returned',
            'category': 'system',
            'priority': 'normal',
            'template': "Good news: Your item '{item_name}' has been marked as claimed and returned."
        },
        'admin_alert_new_report': {
            'title': 'New Item Needs Review',
            'category': 'admin',
            'priority': 'high',
            'template': "A new report for '{item_name}' has been submitted and needs your approval."
        },
        'match_detected': {
            'title': 'We found a match!',
            'category': 'activity',
            'priority': 'high',
            'template': "Good news! We found a possible match for your item: '{item_name}'. Take a look at the matching items now."
        }
    }

    @staticmethod
    def _send_email_async(subject, plain_message, html_message, recipient_email):
        """Internal helper to send email in a separate thread."""
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=None,
                recipient_list=[recipient_email],
                html_message=html_message,
                fail_silently=True,
            )
        except Exception as e:
            logger.error(f"EMAIL ERROR: Failed to send to {recipient_email}. Error: {e}", exc_info=True)

    @classmethod
    def send_status_notification(cls, recipient, item, status_trigger, rejection_reason=None):
        """
        Creates a Notification record and triggers an async email.
        Now supports categories, priorities, and specific humanized wording.
        """
        if not recipient or not recipient.email:
            return

        # 1. Fetch Configuration or Fallback to AI
        config = cls.TRIGGER_CONFIG.get(status_trigger)
        
        if config:
            title = config['title']
            category = config['category']
            priority = config['priority']
            message = config['template'].format(
                item_name=item.name,
                reason=rejection_reason or "No specific reason provided."
            )
        else:
            # Fallback to AI for unmapped/custom triggers
            title = "System Update"
            category = 'system'
            priority = 'normal'
            # Placeholder for thread resolution
            message = "Processing update details..."

        # 2. Save to Database with new metadata
        models.Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            category=category,
            priority=priority,
            rejection_reason=rejection_reason,
            related_item=item,
            status_trigger=status_trigger
        )

        # 3. Prepare Email
        subject = f"Campus Lost & Found: {title}"
        context = {
            'user': recipient,
            'title': title,
            'message': message,
            'item': item,
            'priority': priority,
            'category': category,
        }

        try:
            html_message = render_to_string('item/email/status_update.html', context)
        except:
            html_message = f"<h3>{title}</h3><p>{message}</p>"

        plain_message = strip_tags(html_message)

        # 4. Async Dispatch
        def dispatch():
            try:
                # Resolve content within the thread if AI is needed
                if not config:
                    msg = ai_service.generate_notification_message(item, status_trigger)
                    # Update the record with the generated message
                    models.Notification.objects.filter(
                        recipient=recipient, related_item=item, status_trigger=status_trigger
                    ).update(message=msg)
                    
                    # Update local variable for email
                    context['message'] = msg
                
                # Re-render or send email
                cls._send_email_async(subject, strip_tags(message), html_message, recipient.email)
            except Exception as e:
                logger.error(f"NOTIFICATION THREAD ERROR: {e}", exc_info=True)

        threading.Thread(target=dispatch).start()

    @classmethod
    def notify_match_detected(cls, item, matches):
        """Notifies both parties when a potential match is found."""
        if not item.owner:
            return

        cls.send_status_notification(item.owner, item, 'match_detected')

        if item.verification_status == 'approved':
            for match in matches:
                if match.owner and match.owner != item.owner:
                    cls.send_status_notification(match.owner, match, 'match_detected')

    @classmethod
    def notify_admins(cls, item, trigger='admin_alert_new_report'):
        """Alerts staff members about new reports (High Priority)."""
        # Determine admins
        admins = User.objects.filter(is_staff=True) | User.objects.filter(userprofile__user_type__in=['admin', 'superadmin'])
        admins = admins.distinct()

        for admin in admins:
            if admin != item.owner:
                cls.send_status_notification(admin, item, trigger)
