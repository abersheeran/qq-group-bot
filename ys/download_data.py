import json
from pathlib import Path

from bs4 import BeautifulSoup
from cool import F
import httpx


HERE = Path(__file__).absolute().parent
CHARACTERS_FILE = HERE / "characters.json"


def parse_characters(page: str):
    html = BeautifulSoup(page, features="html.parser")
    table = html.find("table", id="CardSelectTr")

    tr = table.find("tr", id="CardSelectTabHeader")
    title_array = []
    for th in tr.find_all("th"):
        th.get_text().strip() | F(title_array.append)

    tbody = table.find("tbody")
    character_array = []
    for tr in tbody.find_all("tr"):
        if tr.attrs.get("id") == "CardSelectTabHeader":
            continue
        td_array = [td for td in tr.find_all("td")]
        zip(title_array, td_array) | F(dict) | F(character_array.append)

    characters = []
    for character in character_array:
        character_data = {}
        td = character.pop("证件照")
        if img := td.find("img"):
            character_data["photo"] = img.attrs["src"]
        else:
            character_data["photo"] = None
        character_data["name"] = character.pop("名称").get_text().strip()
        character_data["rarity"] = character.pop("稀有度").get_text().strip()
        character_data["weapon"] = character.pop("武器").get_text().strip()
        character_data["element"] = character.pop("元素").get_text().strip()
        character_data["max_health_points"] = character.pop("90生命").get_text().strip()
        character_data["max_attack"] = character.pop("90攻击力").get_text().strip()
        character_data["max_defense"] = character.pop("90防御力").get_text().strip()
        character_data["breakout_increase"] = (
            character.pop("突破加成MAX").get_text().strip()
        )
        td = character.pop("突破材料")
        character_data["materials_needed_for_breakthrough"] = (
            materials_needed_for_breakthrough
        ) = []
        for a in td.find_all("a"):
            name = a.attrs["title"]
            image = a.find("img").attrs["src"]
            materials_needed_for_breakthrough.append({"name": name, "image": image})
        td = character.pop("天赋材料")
        character_data["materials_needed_for_talent"] = materials_needed_for_talent = []
        for a in td.find_all("a"):
            name = a.attrs["title"]
            image = a.find("img").attrs["src"]
            materials_needed_for_talent.append({"name": name, "image": image})
        characters.append(character_data)
    return characters


def download_characters():
    response = httpx.get(
        "https://wiki.biligame.com/ys/%E8%A7%92%E8%89%B2%E6%B6%88%E8%80%97%E6%9D%90%E6%96%99%E4%B8%80%E8%A7%88"
    )
    response.raise_for_status()
    characters = parse_characters(response.text)
    CHARACTERS_FILE.write_text(
        characters | F(json.dumps, ..., indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main():
    download_characters()


if __name__ == "__main__":
    main()
