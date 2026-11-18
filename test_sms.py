import requests

BASE_URL = 'http://127.0.0.1:8000'

def test_sms():
    session = requests.Session()

    print("1. Fetching login page & CSRF token...")
    r = session.get(f"{BASE_URL}/login/")
    assert r.status_code == 200, f"Login page failed: {r.status_code}"
    csrf_token = session.cookies.get('csrftoken')
    print("   Login page loaded successfully.")

    print("2. Authenticating as Principal ('principal')...")
    login_data = {
        'username': 'principal',
        'password': 'Password123!',
        'csrfmiddlewaretoken': csrf_token
    }
    r = session.post(f"{BASE_URL}/login/", data=login_data, headers={'Referer': f"{BASE_URL}/login/"})
    print(f"   Login response status: {r.status_code}, URL: {r.url}")

    print("3. Checking Admin Dashboard...")
    r = session.get(f"{BASE_URL}/dashboard/admin/")
    print(f"   Admin Dashboard status: {r.status_code}, URL: {r.url}")
    assert r.status_code == 200 and "System Control & Analytics Dashboard" in r.text
    print("   Admin Dashboard rendered with stats and charts!")

    print("4. Checking Classes & Sections Page...")
    r = session.get(f"{BASE_URL}/academics/classes/")
    assert r.status_code == 200, f"Classes page failed: {r.status_code}"
    assert "Grade 10" in r.text
    print("   Classes & Sections page rendered correctly.")

    print("5. Checking SIS Student Directory...")
    r = session.get(f"{BASE_URL}/students/")
    assert r.status_code == 200, f"Students directory failed: {r.status_code}"
    assert "John Smith Jr." in r.text
    print("   SIS Student Directory listed demo students!")

    print("6. Testing Student ID Card PDF Generation...")
    r = session.get(f"{BASE_URL}/students/1/id-card/")
    assert r.status_code == 200, f"ID Card PDF failed: {r.status_code}"
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.content.startswith(b'%PDF'), "Response is not a valid PDF binary"
    print("   ReportLab Student ID Card PDF binary verified successfully! (Size: %d bytes)" % len(r.content))

    print("\n[SUCCESS] ALL END-TO-END SMS TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    test_sms()
