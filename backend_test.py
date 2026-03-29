#!/usr/bin/env python3
"""
Backend API testing for SingleStore Diagnostics Dashboard
Tests all endpoints with the sample report file.
"""
import requests
import sys
import time
import json
from pathlib import Path

class SDBInsightAPITester:
    def __init__(self, base_url="https://sdb-insight.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.report_id = None
        self.sample_file = "/tmp/report.tar.gz"

    def log(self, message):
        print(f"[TEST] {message}")

    def run_test(self, name, method, endpoint, expected_status, data=None, files=None, params=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'} if not files else {}

        self.tests_run += 1
        self.log(f"Testing {name}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params)
            elif method == 'POST':
                if files:
                    response = requests.post(url, files=files)
                else:
                    response = requests.post(url, json=data, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                self.log(f"✅ {name} - Status: {response.status_code}")
                try:
                    return True, response.json()
                except:
                    return True, response.text
            else:
                self.log(f"❌ {name} - Expected {expected_status}, got {response.status_code}")
                self.log(f"   Response: {response.text[:200]}")
                return False, {}

        except Exception as e:
            self.log(f"❌ {name} - Error: {str(e)}")
            return False, {}

    def test_health_check(self):
        """Test API health endpoint"""
        return self.run_test("Health Check", "GET", "", 200)

    def test_upload_report(self):
        """Test report upload"""
        if not Path(self.sample_file).exists():
            self.log(f"❌ Sample file not found: {self.sample_file}")
            return False, {}
        
        with open(self.sample_file, 'rb') as f:
            files = {'file': ('report.tar.gz', f, 'application/gzip')}
            success, response = self.run_test(
                "Upload Report", 
                "POST", 
                "reports/upload", 
                200, 
                files=files
            )
            if success and 'id' in response:
                self.report_id = response['id']
                self.log(f"   Report ID: {self.report_id}")
            return success, response

    def test_list_reports(self):
        """Test listing reports"""
        return self.run_test("List Reports", "GET", "reports", 200)

    def test_report_status(self):
        """Test report status endpoint"""
        if not self.report_id:
            self.log("❌ No report ID available for status check")
            return False, {}
        return self.run_test("Report Status", "GET", f"reports/{self.report_id}/status", 200)

    def wait_for_processing(self, max_wait=30):
        """Wait for report to finish processing"""
        if not self.report_id:
            return False
        
        self.log(f"Waiting for report {self.report_id} to finish processing...")
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            success, response = self.test_report_status()
            if success and response.get('status') == 'ready':
                self.log(f"✅ Report processing completed in {time.time() - start_time:.1f}s")
                return True
            elif success and response.get('status') == 'error':
                self.log(f"❌ Report processing failed: {response.get('error', 'Unknown error')}")
                return False
            
            time.sleep(2)
        
        self.log(f"❌ Report processing timeout after {max_wait}s")
        return False

    def test_report_overview(self):
        """Test report overview endpoint"""
        if not self.report_id:
            return False, {}
        return self.run_test("Report Overview", "GET", f"reports/{self.report_id}/overview", 200)

    def test_report_nodes(self):
        """Test report nodes endpoint"""
        if not self.report_id:
            return False, {}
        return self.run_test("Report Nodes", "GET", f"reports/{self.report_id}/nodes", 200)

    def test_report_storage(self):
        """Test report storage endpoint"""
        if not self.report_id:
            return False, {}
        return self.run_test("Report Storage", "GET", f"reports/{self.report_id}/storage", 200)

    def test_report_queries(self):
        """Test report queries endpoint"""
        if not self.report_id:
            return False, {}
        return self.run_test("Report Queries", "GET", f"reports/{self.report_id}/queries", 200)

    def test_report_logs(self):
        """Test report logs endpoint with filters"""
        if not self.report_id:
            return False, {}
        
        # Test basic logs
        success1, _ = self.run_test("Report Logs", "GET", f"reports/{self.report_id}/logs", 200)
        
        # Test with filters
        params = {"severity": "ERROR,WARN", "page": 1, "page_size": 50}
        success2, _ = self.run_test("Report Logs (Filtered)", "GET", f"reports/{self.report_id}/logs", 200, params=params)
        
        return success1 and success2, {}

    def test_report_recommendations(self):
        """Test report recommendations endpoint"""
        if not self.report_id:
            return False, {}
        return self.run_test("Report Recommendations", "GET", f"reports/{self.report_id}/recommendations", 200)

    def test_delete_report(self):
        """Test report deletion"""
        if not self.report_id:
            return False, {}
        return self.run_test("Delete Report", "DELETE", f"reports/{self.report_id}", 200)

    def run_all_tests(self):
        """Run complete test suite"""
        self.log("Starting SDB Insight API Tests")
        self.log("=" * 50)

        # Basic health check
        self.test_health_check()

        # Upload and processing workflow
        upload_success, _ = self.test_upload_report()
        if not upload_success:
            self.log("❌ Upload failed, stopping tests")
            return self.get_results()

        # Wait for processing
        if not self.wait_for_processing():
            self.log("❌ Processing failed, stopping tests")
            return self.get_results()

        # Test all data endpoints
        self.test_list_reports()
        self.test_report_overview()
        self.test_report_nodes()
        self.test_report_storage()
        self.test_report_queries()
        self.test_report_logs()
        self.test_report_recommendations()

        # Cleanup
        self.test_delete_report()

        return self.get_results()

    def get_results(self):
        """Get test results summary"""
        self.log("=" * 50)
        self.log(f"Tests completed: {self.tests_passed}/{self.tests_run} passed")
        
        if self.tests_passed == self.tests_run:
            self.log("✅ All tests passed!")
            return 0
        else:
            self.log(f"❌ {self.tests_run - self.tests_passed} tests failed")
            return 1

def main():
    tester = SDBInsightAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())