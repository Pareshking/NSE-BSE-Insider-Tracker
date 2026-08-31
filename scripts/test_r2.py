import os
from datetime import datetime, timezone

import boto3


def main() -> None:
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    access_key = os.environ["R2_ACCESS_KEY_ID"]
    secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
    bucket = os.environ["R2_BUCKET_NAME"]

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    key = "_system/connection-test.txt"
    body = f"R2 connection OK: {datetime.now(timezone.utc).isoformat()}\n"

    client.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
    response = client.get_object(Bucket=bucket, Key=key)
    returned = response["Body"].read().decode("utf-8")

    if returned != body:
        raise RuntimeError("R2 read-back verification failed")

    print(f"R2 connection and read-back successful: s3://{bucket}/{key}")


if __name__ == "__main__":
    main()
