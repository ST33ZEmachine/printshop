import json
import csv

INPUT_FILE = "board-archive-2021-0707.json"
OUTPUT_FILE = "trello_cards_20210707.csv"

def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    board_id = data.get("id")
    board_name = data.get("name")

    # Map list_id -> list_name
    lists_by_id = {
        lst["id"]: lst.get("name")
        for lst in data.get("lists", [])
    }

    # Prepare CSV writer
    fieldnames = [
        "card_id",
        "board_id",
        "board_name",
        "list_id",
        "list_name",
        "name",              # card title
        "desc",              # description
        "labels",            # comma-separated label names
        "closed",            # archived?
        "due",
        "dateLastActivity",
        "shortUrl",
    ]

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for card in data.get("cards", []):
            list_id = card.get("idList")
            list_name = lists_by_id.get(list_id)

            # Card labels: usually an array of objects with "name"
            label_names = []
            for lbl in card.get("labels", []):
                name = (lbl.get("name") or "").strip()
                if name:
                    label_names.append(name)
            labels_str = ", ".join(label_names)

            row = {
                "card_id": card.get("id"),
                "board_id": board_id,
                "board_name": board_name,
                "list_id": list_id,
                "list_name": list_name,
                "name": card.get("name"),
                "desc": card.get("desc"),
                "labels": labels_str,
                "closed": card.get("closed"),
                "due": card.get("due"),
                "dateLastActivity": card.get("dateLastActivity"),
                "shortUrl": card.get("shortUrl"),
            }
            writer.writerow(row)

    print(f"Wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
