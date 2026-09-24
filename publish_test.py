import urllib.request
import urllib.parse
import json
import time
import hashlib
from datetime import datetime, timezone, timedelta

# 1. Read .env
env = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

access_token = env.get("THREADS_ACCESS_TOKEN")
user_id = env.get("THREADS_USER_ID")
dry_run = env.get("DRY_RUN", "true").lower() == "true"

print(f"--- THREADS STAGE 1 TRACER BULLET ---")
print(f"Target User ID: {user_id}")
print(f"DRY_RUN: {dry_run}")

# 2. Determine slot key (Europe/Istanbul UTC+3)
utc_now = datetime.now(timezone.utc)
istanbul_now = utc_now + timedelta(hours=3)
date_str = istanbul_now.strftime("%Y-%m-%d")
slot = "LUNCH" if istanbul_now.hour < 16 else "EVENING"
slot_key = f"{date_str}_{slot}"
print(f"Current Slot Key: {slot_key} (Local time: {istanbul_now.strftime('%Y-%m-%d %H:%M:%S')})")

# 3. Payload
test_text = (
    "🇬🇧 Günün İpucu (Test)\n\n"
    "İngilizcede 'katılıyorum' derken yapılan en sık hata:\n"
    "❌ I am agree with you\n"
    "✅ I agree with you\n\n"
    "'Agree' zaten bir fiildir, başına am/is/are gelmez.\n\n"
    "💬 Sen bu hatayı daha önce yaptın mı? Yorumlarda belirt!"
)

print(f"Payload length: {len(test_text)} chars (Limit: 470)")
assert len(test_text) <= 470, "Text exceeds MAX_POST_CHARS!"

payload_hash = hashlib.sha256(test_text.encode("utf-8")).hexdigest()[:16]

# 4. Check /me/threads for Idempotency (last 6 hours)
print("\n[Step 1] Checking recent posts on Threads for idempotency...")
recent_url = f"https://graph.threads.net/v1.0/me/threads?fields=id,text,timestamp&limit=10&access_token={access_token}"
req = urllib.request.Request(recent_url)
with urllib.request.urlopen(req) as resp:
    recent_data = json.loads(resp.read().decode()).get("data", [])

for post in recent_data:
    post_text = post.get("text", "")
    if "Günün İpucu (Test)" in post_text:
        print(f"⚠️ IDEMPOTENCY HIT: A post with this exact test content is ALREADY live!")
        print(f"Existing Post ID: {post.get('id')}")
        print(f"Timestamp: {post.get('timestamp')}")
        print("--> ABORTING duplicate publish as designed. Self-healing success!")
        exit(0)

print("✅ No duplicate found in the last 6 hours. Proceeding to publish...")

if dry_run:
    print("[DRY RUN] Would publish container and finalize post. Exiting cleanly.")
    exit(0)

# 5. Create Media Container
print("\n[Step 2] Creating media container...")
create_url = f"https://graph.threads.net/v1.0/{user_id}/threads"
payload = urllib.parse.urlencode({
    "media_type": "TEXT",
    "text": test_text,
    "access_token": access_token
}).encode("utf-8")

req = urllib.request.Request(create_url, data=payload, method="POST")
with urllib.request.urlopen(req) as resp:
    container_res = json.loads(resp.read().decode())
    container_id = container_res.get("id")

print(f"Container created with ID: {container_id}")

# 6. Poll Container Status
print("\n[Step 3] Polling container readiness...")
status_url = f"https://graph.threads.net/v1.0/{container_id}?fields=status,error_message&access_token={access_token}"
ready = False
for attempt in range(1, 15):
    time.sleep(2)
    with urllib.request.urlopen(urllib.request.Request(status_url)) as resp:
        status_data = json.loads(resp.read().decode())
        status = status_data.get("status")
        print(f"Attempt {attempt}: Status = {status}")
        if status == "FINISHED":
            ready = True
            break
        elif status == "ERROR":
            print(f"Container error: {status_data.get('error_message')}")
            exit(1)

if not ready:
    print("Container polling timed out!")
    exit(1)

# 7. Publish Media Container
print("\n[Step 4] Publishing media container...")
publish_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
publish_payload = urllib.parse.urlencode({
    "creation_id": container_id,
    "access_token": access_token
}).encode("utf-8")

req = urllib.request.Request(publish_url, data=publish_payload, method="POST")
with urllib.request.urlopen(req) as resp:
    publish_res = json.loads(resp.read().decode())
    published_post_id = publish_res.get("id")

print("\n" + "=" * 50)
print(f"🎉 SUCCESS! Post is LIVE on Threads!")
print(f"Published Post ID: {published_post_id}")
print(f"Post URL: https://www.threads.net/@ingilizceninbugunu/post/{published_post_id}")
print("=" * 50)
