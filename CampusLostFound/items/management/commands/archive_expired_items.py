"""
Management command to auto-archive expired items.
Run via: python manage.py archive_expired_items
Schedule with cron or Windows Task Scheduler for daily execution.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from items.models import Item, Notification
from items import ai_service


class Command(BaseCommand):
    help = 'Archive expired items and send expiry warning notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be archived without actually doing it',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()

        # 1. Send warning notifications for items expiring in 3 days
        warning_threshold = now + timedelta(days=3)
        expiring_soon = Item.objects.filter(
            expires_at__lte=warning_threshold,
            expires_at__gt=now,
            status__in=['lost', 'found'],
            is_approved=True,
        )

        warned_count = 0
        for item in expiring_soon:
            # Only warn once - check if we already sent an expiry warning
            already_warned = Notification.objects.filter(
                related_item=item,
                status_trigger='expiry_warning',
            ).exists()

            if not already_warned and item.owner:
                if not dry_run:
                    days_left = (item.expires_at - now).days
                    message = (
                        f'Your item "{item.name}" will be archived in {days_left} day(s). '
                        f'Visit your dashboard to renew it if it\'s still relevant.'
                    )
                    Notification.objects.create(
                        recipient=item.owner,
                        message=message,
                        related_item=item,
                        status_trigger='expiry_warning',
                    )
                warned_count += 1

        # 2. Archive expired items
        expired_items = Item.objects.filter(
            expires_at__lte=now,
            status__in=['lost', 'found'],
        )

        archived_count = 0
        for item in expired_items:
            if not dry_run:
                item.status = 'archived'
                item.save(update_fields=['status'])

                # Notify owner
                if item.owner:
                    message = (
                        f'Your item "{item.name}" has been automatically archived after 30 days. '
                        f'You can renew it from your dashboard if needed.'
                    )
                    Notification.objects.create(
                        recipient=item.owner,
                        message=message,
                        related_item=item,
                        status_trigger='item_archived',
                    )
            archived_count += 1

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Sent {warned_count} expiry warning(s). '
            f'Archived {archived_count} expired item(s).'
        ))
