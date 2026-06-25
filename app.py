
import re
from io import BytesIO
from collections import Counter
from datetime import date
import pandas as pd
import requests
import streamlit as st
from pypdf import PdfReader

BASE = "https://loto.mk"

st.set_page_config(page_title="Лото 7/37 Анализатор v2", layout="wide")

def zone(n: int) -> int:
    if n <= 9: return 1
    if n <= 18: return 2
    if n <= 27: return 3
    return 4

def zone_pattern(nums):
    z = [0,0,0,0]
    for n in nums:
        z[zone(n)-1] += 1
    return "-".join(map(str,z))

def adjacent_pairs(nums):
    s = sorted(nums)
    return sum(1 for a,b in zip(s,s[1:]) if b-a == 1)

def candidate_pdf_urls(year, kolo):
    # На loto.mk извештаите најчесто се именувани вака:
    names = [
        f"izvestaj_{kolo}_kolo_{year}_Loto7_i_Joker.pdf",
        f"izvestaj_{kolo}_kolo_{year}_Loto7_Joker.pdf",
        f"izvestaj_{kolo}_kolo_{year}_loto7_i_joker.pdf",
        f"izvestaj_{kolo}_kolo_{year}_Loto_7_i_Joker.pdf",
        f"izvestaj_{kolo}_kolo_{year}_Loto7_i_Dzoker.pdf",
        f"izvestaj_{kolo}_kolo_{year}_Loto7_i_Joker.pdf".replace("Joker","Djoker"),
        f"Izvestaj_{kolo}_kolo_{year}_Loto7_i_Joker.pdf",
    ]
    folders = [
        "/DLSFiles/Dokumenti/IZVESTAJI/",
        "/DLSFiles/Dokumenti/Izvestaji/",
        "/DLSFiles/Dokumenti/izvestaji/",
    ]
    return [BASE + folder + name for folder in folders for name in names]

@st.cache_data(show_spinner=False)
def download_pdf(url):
    headers = {"User-Agent":"Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=25)
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        return r.content
    return None

def pdf_to_text(content):
    reader = PdfReader(BytesIO(content))
    txt = ""
    for page in reader.pages:
        txt += "\n" + (page.extract_text() or "")
    return txt

def extract_draw_numbers(text):
    # Најсигурно: бара линија околу "Добитна комбинација"
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    key_lines = []
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "добитна" in low or "kombinacija" in low or "комбинација" in low or "лото 7/37" in low:
            key_lines.append(" ".join(lines[max(0,i-2):i+3]))
    search_blocks = key_lines + lines + [text]
    for block in search_blocks:
        nums = [int(x) for x in re.findall(r"\b(?:[1-9]|[12][0-9]|3[0-7])\b", block)]
        for i in range(len(nums)-6):
            g = nums[i:i+7]
            if len(set(g)) == 7 and all(1 <= n <= 37 for n in g):
                # Избегни групи од фондови/проценти така што бараме разумна сума
                if 55 <= sum(g) <= 210:
                    return g
    return None

def find_pdf_for_draw(year, kolo):
    for url in candidate_pdf_urls(year, kolo):
        content = download_pdf(url)
        if content:
            return url, content
    return None, None

def build_db(year_from, year_to, max_kolo):
    rows = []
    total = (year_to-year_from+1)*max_kolo
    done = 0
    prog = st.progress(0)
    status = st.empty()

    for year in range(year_from, year_to+1):
        miss_in_row = 0
        for kolo in range(1, max_kolo+1):
            done += 1
            status.text(f"Проверувам {year}, коло {kolo}...")
            prog.progress(done/total)

            url, content = find_pdf_for_draw(year, kolo)
            if not content:
                miss_in_row += 1
                # ако сме во тековна година и има многу празни по последното коло, прекини ја годината
                if year == year_to and miss_in_row >= 8 and kolo > 10:
                    break
                continue

            miss_in_row = 0
            try:
                text = pdf_to_text(content)
                nums = extract_draw_numbers(text)
                if nums:
                    rows.append({
                        "Година": year,
                        "Коло": kolo,
                        "Б1": nums[0], "Б2": nums[1], "Б3": nums[2], "Б4": nums[3],
                        "Б5": nums[4], "Б6": nums[5], "Б7": nums[6],
                        "PDF": url
                    })
            except Exception as e:
                rows.append({"Година": year, "Коло": kolo, "Грешка": str(e), "PDF": url})

    prog.empty()
    status.empty()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    nums_cols = [f"Б{i}" for i in range(1,8)]
    df = df.dropna(subset=nums_cols).copy()
    for c in nums_cols:
        df[c] = df[c].astype(int)
    df["Броеви"] = df[nums_cols].astype(str).agg(", ".join, axis=1)
    df["Зонски распоред"] = df[nums_cols].apply(lambda r: zone_pattern(list(r)), axis=1)
    df["Сума"] = df[nums_cols].sum(axis=1)
    df["Парни"] = df[nums_cols].apply(lambda r: sum(int(x)%2==0 for x in r), axis=1)
    df["Непарни"] = 7 - df["Парни"]
    df["Соседни парови"] = df[nums_cols].apply(lambda r: adjacent_pairs(list(r)), axis=1)
    return df.sort_values(["Година","Коло"]).reset_index(drop=True)

def frequency_table(df):
    nums_cols = [f"Б{i}" for i in range(1,8)]
    all_nums = []
    for c in nums_cols:
        all_nums += df[c].astype(int).tolist()
    cnt = Counter(all_nums)
    return pd.DataFrame({"Број": range(1,38), "Појавувања": [cnt.get(i,0) for i in range(1,38)]})

def generate_by_patterns(patterns):
    import random
    zones = {
        1:list(range(1,10)),
        2:list(range(10,19)),
        3:list(range(19,28)),
        4:list(range(28,38)),
    }
    rows=[]
    for p in patterns:
        counts = [int(x) for x in p.split("-")]
        nums=[]
        for zi,c in enumerate(counts,1):
            nums += random.sample(zones[zi], c)
        rows.append({"Распоред":p, "Комбинација":" – ".join(map(str, sorted(nums)))})
    return pd.DataFrame(rows)

st.title("Лото 7/37 Анализатор v2")
st.caption("Оваа верзија не зависи од скриената листа на страницата, туку ги пробува познатите PDF адреси по година и коло.")

with st.sidebar:
    st.header("Преземање")
    current_year = date.today().year
    year_from = st.number_input("Од година", 2019, current_year, 2019)
    year_to = st.number_input("До година", 2019, current_year, current_year)
    max_kolo = st.number_input("Макс. кола по година", 50, 120, 105)
    st.warning("Првото преземање може да трае неколку минути.")
    if st.button("Освежи / преземи"):
        st.cache_data.clear()
        st.session_state["load"] = True

if not st.session_state.get("load"):
    st.info("Притисни „Освежи / преземи“ во левото мени.")
    st.stop()

df = build_db(int(year_from), int(year_to), int(max_kolo))

if df.empty:
    st.error("Не најдов PDF извештаи со пробаните имиња. Испрати ми еден точен PDF линк од loto.mk и ќе го додадам шаблонот во апликацијата.")
    st.stop()

st.success(f"Успешно прочитани {len(df)} кола.")
st.dataframe(df, use_container_width=True)

st.download_button(
    "Симни CSV",
    df.to_csv(index=False).encode("utf-8-sig"),
    "loto_737_baza.csv",
    "text/csv"
)

c1,c2,c3,c4 = st.columns(4)
c1.metric("Кола", len(df))
c2.metric("Различни распореди", df["Зонски распоред"].nunique())
c3.metric("Просечна сума", round(df["Сума"].mean(),2))
c4.metric("Прос. соседни парови", round(df["Соседни парови"].mean(),2))

st.subheader("Фреквенција на броеви")
freq = frequency_table(df).sort_values(["Појавувања","Број"], ascending=[False, True])
st.dataframe(freq, use_container_width=True)

st.subheader("Зонски распореди")
patterns = df["Зонски распоред"].value_counts().reset_index()
patterns.columns = ["Распоред","Пати"]
st.dataframe(patterns, use_container_width=True)

st.subheader("Генератор")
top_patterns = patterns["Распоред"].head(7).tolist()
st.write("Комбинации според најчестите распореди:")
st.dataframe(generate_by_patterns(top_patterns), use_container_width=True)

manual = st.text_input("Рачни распореди, одвоени со запирка", "1-2-2-2,2-1-2-2,2-2-1-2,3-2-1-1,1-1-2-3")
manual_patterns = [x.strip() for x in manual.split(",") if re.match(r"^\d-\d-\d-\d$", x.strip()) and sum(map(int,x.strip().split("-"))) == 7]
if st.button("Генерирај рачно"):
    st.dataframe(generate_by_patterns(manual_patterns), use_container_width=True)
