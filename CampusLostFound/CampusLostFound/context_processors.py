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
