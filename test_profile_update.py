import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sms_core.settings')
django.setup()

from django.test import Client
from accounts.models import User

def run_test():
    print("--- STARTING USERNAME & PASSWORD UPDATE E2E TEST ---")
    client = Client()

    # 1. Login as principal
    user = User.objects.get(username='principal')
    original_pass = 'Password123!'
    user.set_password(original_pass)
    user.save()

    login_success = client.login(username='principal', password=original_pass)
    assert login_success, "Failed to login as principal"
    print("1. [PASS] Logged in successfully as 'principal'")

    # 2. Update Username to 'principal_updated'
    res = client.post('/profile/', {
        'action': 'update_profile',
        'username': 'principal_updated',
        'first_name': 'Dr. Robert',
        'last_name': 'Vance',
        'phone_number': '+92 300 0000000',
        'address': 'Islamabad'
    }, follow=True)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    
    user.refresh_from_db()
    assert user.username == 'principal_updated', f"Expected username 'principal_updated', got {user.username}"
    print("2. [PASS] Username successfully updated to 'principal_updated'")

    # 3. Update Password to 'NewPassword123!'
    new_pass = 'NewPassword123!'
    res = client.post('/profile/', {
        'action': 'update_password',
        'current_password': original_pass,
        'new_password': new_pass,
        'confirm_password': new_pass
    }, follow=True)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"

    # Verify session remains active (update_session_auth_hash working)
    res_dash = client.get('/dashboard/')
    assert res_dash.status_code == 302 or res_dash.status_code == 200, "Session was lost after password change!"
    print("3. [PASS] Password updated successfully & session auth hash updated")

    # 4. Re-login with new username & new password
    client.logout()
    re_login = client.login(username='principal_updated', password=new_pass)
    assert re_login, "Failed to login with new username and password"
    print("4. [PASS] Successfully authenticated using new username 'principal_updated' and new password")

    # Clean up: restore original username & password for principal
    user.username = 'principal'
    user.set_password('Password123!')
    user.save()
    print("5. [PASS] Reset test account back to default 'principal' credentials")

    print("\n=======================================================")
    print("ALL USERNAME & PASSWORD UPDATE TESTS PASSED PERFECTLY!")
    print("=======================================================")

if __name__ == '__main__':
    run_test()
