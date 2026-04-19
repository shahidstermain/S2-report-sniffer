import os
from unittest.mock import MagicMock, patch
from backend.s3_client import upload_to_s3

def test_s3_upload_mock():
    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client):
        upload_to_s3("dummy.txt", "my-bucket", "dummy.txt")
    mock_client.upload_file.assert_called_once_with("dummy.txt", "my-bucket", "dummy.txt")
