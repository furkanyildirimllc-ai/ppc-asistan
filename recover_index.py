import json

transcript_path = "/Users/furkanyildirimllc/.gemini/antigravity-cli/brain/182af389-48c9-471e-b579-ebf1a841f4df/.system_generated/logs/transcript_full.jsonl"
target_file = "/Users/furkanyildirimllc/Claude/ppc-tool/static/index.html"

# Read original file
with open(target_file, "r") as f:
    content = f.read()

changes = []
with open(transcript_path, "r") as f:
    for line in f:
        try:
            step = json.loads(line)
        except:
            continue
        
        if step.get("type") == "PLANNER_RESPONSE" and "tool_calls" in step:
            for call in step["tool_calls"]:
                if call["name"] == "default_api:replace_file_content" or call["name"] == "replace_file_content":
                    args = call.get("args", {})
                    if args.get("TargetFile") == target_file:
                        changes.append(args)
                elif call["name"] == "default_api:multi_replace_file_content" or call["name"] == "multi_replace_file_content":
                    args = call.get("args", {})
                    if args.get("TargetFile") == target_file:
                        for chunk in args.get("ReplacementChunks", []):
                            changes.append(chunk)

print(f"Found {len(changes)} replacement operations.")

for change in changes:
    target = change.get("TargetContent")
    replacement = change.get("ReplacementContent")
    
    if target and target in content:
        content = content.replace(target, replacement, 1)
        print("Applied a change.")
    else:
        print("Failed to apply a change! Target content not found.")
        print("Target was:", repr(target)[:100])

with open(target_file + ".recovered", "w") as f:
    f.write(content)
print("Recovered file saved to", target_file + ".recovered")
