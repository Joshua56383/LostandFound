from django.shortcuts import render, redirect
from items.forms import CustomUserCreationForm
from django.contrib.auth import login

def signup(request):
    # Determine base template (partial if loaded via AJAX/Modal)
    base_template = 'base.html'
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('partial'):
        base_template = '_partial.html'

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('items:dashboard')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'user/signup.html', {
        'form': form,
        'base_template': base_template
    })
