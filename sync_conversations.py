#!/usr/bin/env python3
import os
import shutil
import sys
import argparse

# Default Antigravity brain storage path
BRAIN_DIR = os.path.expanduser('~/.gemini/antigravity/brain')
# Storage path inside the project
PROJECT_CONVS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'conversations')

def export_conv(conv_id):
    src_dir = os.path.join(BRAIN_DIR, conv_id)
    if not os.path.exists(src_dir):
        print(f"Error: Conversation {conv_id} not found in {BRAIN_DIR}")
        return False
    
    dest_dir = os.path.join(PROJECT_CONVS_DIR, conv_id)
    os.makedirs(dest_dir, exist_ok=True)
    
    # Files to copy for history restore
    targets = [
        'implementation_plan.md',
        'task.md',
        'walkthrough.md',
        '.system_generated/logs/transcript.jsonl',
        '.system_generated/logs/transcript_full.jsonl'
    ]
    
    copied_count = 0
    for target in targets:
        src_path = os.path.join(src_dir, target)
        if os.path.exists(src_path):
            dest_path = os.path.join(dest_dir, target)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {target}")
            copied_count += 1
            
    print(f"Exported conversation {conv_id} to project ({copied_count} files).")
    print("Now you can commit these files to Git!")
    return True

def import_convs():
    if not os.path.exists(PROJECT_CONVS_DIR):
        print("No conversations found in the project.")
        return
        
    for conv_id in os.listdir(PROJECT_CONVS_DIR):
        src_dir = os.path.join(PROJECT_CONVS_DIR, conv_id)
        if not os.path.isdir(src_dir):
            continue
            
        dest_dir = os.path.join(BRAIN_DIR, conv_id)
        os.makedirs(dest_dir, exist_ok=True)
        
        # Recursively copy all files
        for root, dirs, files in os.walk(src_dir):
            rel_path = os.path.relpath(root, src_dir)
            if rel_path == '.':
                target_root = dest_dir
            else:
                target_root = os.path.join(dest_dir, rel_path)
                
            os.makedirs(target_root, exist_ok=True)
            for file in files:
                shutil.copy2(os.path.join(root, file), os.path.join(target_root, file))
                
        print(f"Imported conversation {conv_id} to {BRAIN_DIR}.")
        print(f"You can now resume it in Antigravity using: /resume {conv_id}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sync Antigravity conversations with Git project")
    subparsers = parser.add_subparsers(dest="command")
    
    export_parser = subparsers.add_parser("export", help="Export a conversation to the project")
    export_parser.add_argument("conv_id", help="Conversation ID to export")
    
    subparsers.add_parser("import", help="Import all conversations from the project to this PC")
    
    args = parser.parse_args()
    
    if args.command == "export":
        export_conv(args.conv_id)
    elif args.command == "import":
        import_convs()
    else:
        parser.print_help()
