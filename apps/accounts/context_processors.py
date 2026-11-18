def user_role_context(request):
    """
    Exposes user role properties to all templates.
    """
    if not request.user.is_authenticated:
        return {
            'user_role': None,
            'is_super_admin': False,
            'is_admin': False,
            'is_teacher': False,
            'is_student': False,
            'is_parent': False,
            'is_accountant': False,
            'custom_role': None,
        }
    
    return {
        'user_role': getattr(request.user, 'role', 'STUDENT'),
        'is_super_admin': request.user.is_super_admin,
        'is_admin': request.user.is_admin_or_principal,
        'is_teacher': request.user.is_teacher,
        'is_student': request.user.is_student,
        'is_parent': request.user.is_parent,
        'is_accountant': request.user.is_accountant,
        'custom_role': getattr(request.user, 'custom_role', None),
    }
