from django.conf import settings

def auth_partial_processor(request):
    """
    Sets base_template to _partial.html if requested via AJAX or manual 'partial' flag.
    Used for loading auth pages into modals without recursive inheritance.
    """
    base_template = 'base.html'
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('partial'):
        base_template = '_partial.html'
    
    return {
        'base_template': base_template
    }

def global_counts_processor(request):
    """
    Adds universal counts to the context, such as pending approvals and unread messages.
    Ensures consistency between staff users and 'is_admin' profile flags.
    """
    context = {
        'global_pending_count': 0,
        'unread_chats_count': 0
    }
    if request.user.is_authenticated:
        from items.models import Item, DirectMessage
        
        # 1. Unread Messages for everyone
        context['unread_chats_count'] = DirectMessage.objects.filter(recipient=request.user, is_read=False).count()

        # 2. Admin Pending Queue
        is_admin = request.user.is_staff or getattr(request.user.userprofile, 'is_admin', False)
        if is_admin:
            # Use all_objects to count everything that is pending (even if theoretically soft-deleted)
            context['global_pending_count'] = Item.all_objects.filter(verification_status='pending', deleted_at__isnull=True).count()
            
            from items.models import ClaimRequest
            context['admin_pending_claims_count'] = ClaimRequest.objects.filter(status='pending').count()
        
        from items.models import ClaimRequest
        context['my_activity_indicator_count'] = ClaimRequest.objects.filter(claimer=request.user, status__in=['pending', 'approved']).count()
        
        context['is_admin'] = is_admin
            
    return context

def site_url_processor(request):
    """
    Adds the SITE_URL to the global template context.
    Prioritizes the live request origin for ngrok compatibility.
    """
    # Prefer live request origin to handle dynamic ngrok tunnels seamlessly
    live_origin = request.build_absolute_uri('/').rstrip('/')
    
    # Use settings.SITE_URL if explicitly defined, otherwise use the live origin
    site_url = getattr(settings, 'SITE_URL', '') or live_origin
    
    return {
        'site_url': site_url
    }
