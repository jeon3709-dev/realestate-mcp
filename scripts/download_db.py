"""법정동 코드 DB(data/code_bdong.json) 재생성 스크립트.

원본: jeon3709-dev/LandPrice_MCP download_db.py (출력 경로만 data/ 로 변경)
사용: python scripts/download_db.py
"""
import json
import os
import urllib.request

url = "https://raw.githubusercontent.com/WooilJeong/code/main/code/code_dong/code_bdong.json"
output_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "code_bdong.json")


def main() -> None:
    print(f"Downloading {url}...")
    try:
        with urllib.request.urlopen(url) as response:
            content = response.read().decode('utf-8')
            print("Cleaning up 'nan' float strings...")
            content_cleaned = content.replace("nan", "null")

            # Validate JSON structure
            print("Validating JSON structure...")
            data = json.loads(content_cleaned)
            print(f"Validation successful! Total items: {len(data.get('data', {}).get('법정동코드', {}))}")

            # Save locally
            print(f"Saving to {output_file}...")
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print("Done!")
    except Exception as e:
        print("Error downloading database:", e)


if __name__ == "__main__":
    main()
