from unittest.mock import MagicMock, patch
from backend.s3_client import upload_to_s3

def test_s3_upload_mock():
    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client) as mock_boto_client:
        upload_to_s3("dummy.txt", "my-bucket", "dummy.txt")

    mock_boto_client.assert_called_once_with(
        "s3",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        region_name="us-east-1",
    )
    mock_client.upload_file.assert_called_once_with("dummy.txt", "my-bucket", "dummy.txt")
