# save.py
import os

def save_project_structure(output_file="project_source_code.txt"):
    # پوشه‌هایی که به هیچ وجه نباید واردشان شد (لاگ‌ها، دیتابیس‌ها و محیط‌های مجازی)
    excluded_dirs = {'venv', '*.db', '.venv', '__pycache__', '.git', 'logs', 'data', '.vscode'}
    
    # فقط این فرمت‌ها به عنوان سورس کد شناخته و ذخیره می‌شوند
    allowed_exts = {'.py', '.json', '.md', '.env'}
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for root, dirs, files in os.walk('.'):
            # حذف پوشه‌های نامطلوب از جستجو
            dirs[:] = [d for d in dirs if d not in excluded_dirs and not d.startswith('.')]
            
            for file in sorted(files):
                # بررسی اینکه آیا فایل پسوند مجاز دارد یا دقیقاً فایل .env است
                if any(file.endswith(ext) for ext in allowed_exts) or file == '.env':
                    filepath = os.path.join(root, file)
                    rel_path = os.path.relpath(filepath)
                    
                    f.write(f"\n{'='*60}\n")
                    f.write(f"FILE: {rel_path}\n")
                    f.write(f"{'='*60}\n\n")
                    
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as content_file:
                            content = content_file.read()
                            f.write(content)
                            if not content.endswith('\n'):
                                f.write('\n')
                    except Exception as e:
                        f.write(f"[Error reading file: {e}]\n")

if __name__ == "__main__":
    save_project_structure()
    print("✅ Source code backup saved successfully to 'project_source_code.txt'")