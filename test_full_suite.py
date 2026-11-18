import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sms_core.settings')
django.setup()

import pytest
from django.test import Client, override_settings
from django.core.management import call_command
from accounts.models import User

@pytest.mark.django_db
def test_all():
    with override_settings(DEBUG=True):
        call_command('seed_data')
    client = Client()
    print("1. Logging in as principal...")
    user = User.objects.get(username='principal')
    client.force_login(user)

    print("2. Checking Admin Dashboard...")
    r = client.get('/dashboard/admin/')
    assert r.status_code == 200, f"Admin Dashboard status: {r.status_code}"
    print("   [PASS] Admin Dashboard status 200")

    print("3. Checking Fee Dashboard...")
    r = client.get('/fees/dashboard/')
    assert r.status_code == 200, f"Fee Dashboard status: {r.status_code}"
    print("   [PASS] Fee Dashboard status 200")

    print("4. Checking Fee Vouchers List...")
    r = client.get('/fees/vouchers/')
    assert r.status_code == 200, f"Vouchers list status: {r.status_code}"
    print("   [PASS] Fee Vouchers List status 200")

    print("5. Checking Create Fee Voucher Page...")
    r = client.get('/fees/vouchers/create/')
    assert r.status_code == 200, f"Voucher Create status: {r.status_code}"
    print("   [PASS] Create Fee Voucher Page status 200")

    print("\n[SUCCESS] ALL SUITE TESTS PASSED!")

if __name__ == '__main__':
    test_all()
