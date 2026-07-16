import streamlit as st
import pandas as pd
import os
import tempfile
import traceback

import pymupdf  # PyMuPDF

# ============================================================
# Session State Init
# ============================================================
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.word_data = pd.DataFrame(columns=["WORD / PHRASE", "COMMENT"])
    st.session_state.uploader_key = 0

st.set_page_config(page_title="PDF Highlighter", layout="wide")

# ============================================================
# Core Highlighting Logic (adapted from original script)
# ============================================================

def build_word_map(df):
    """Turns the WORD/COMMENT dataframe into the dict the highlighter needs.
    If COMMENT is blank, falls back to a default comment string."""
    word_map = {}
    if df is None or df.empty:
        return word_map
    for _, row in df.iterrows():
        word = str(row.get("WORD / PHRASE", "")).strip()
        if not word or word.lower() == "nan":
            continue
        comment = str(row.get("COMMENT", "")).strip()
        if not comment or comment.lower() == "nan":
            comment = f"Review target keyword: {word}"
        word_map[word] = comment
    return word_map


def highlight_words_in_pdf(input_bytes, word_map):
    """Opens the PDF from bytes, highlights every match of every word/phrase,
    attaches the comment as an annotation note, and returns the output bytes
    plus a per-word match count for feedback."""
    pdf_document = pymupdf.open(stream=input_bytes, filetype="pdf")
    match_counts = {word: 0 for word in word_map}

    for page_number in range(len(pdf_document)):
        page = pdf_document.load_page(page_number)
        for word_to_highlight, comment in word_map.items():
            if not word_to_highlight:
                continue
            instances = page.search_for(word_to_highlight)
            for inst in instances:
                highlight = page.add_highlight_annot(inst)
                highlight.set_info(content=comment, title="Review Note")
                highlight.update()
                match_counts[word_to_highlight] += 1

    output_bytes = pdf_document.tobytes()
    pdf_document.close()
    return output_bytes, match_counts


def parse_pasted_words(text):
    """Parses text copied straight out of a spreadsheet column (or two columns).
    Handles:
      - a single column of words (one per line) -> comment auto-generated
      - two tab-separated columns (word, comment) copied together
    Also tolerates commas as a separator if no tabs are present."""
    rows = []
    for raw_line in text.strip().split("\n"):
        line = raw_line.rstrip("\r").strip()
        if not line:
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
        elif "," in line:
            parts = [p.strip() for p in line.split(",", 1)]
        else:
            parts = [line]

        parts = [p for p in parts if p != ""]
        if not parts:
            continue

        word = parts[0]
        comment = parts[1] if len(parts) > 1 else f"Review target keyword: {word}"
        rows.append({"WORD / PHRASE": word, "COMMENT": comment})

    return pd.DataFrame(rows, columns=["WORD / PHRASE", "COMMENT"])


def sanitize_word_df(df, fallback_df):
    """Keeps the data_editor's dataframe safe no matter what gets pasted/typed
    into it. Never raises; falls back to the last known-good table on failure."""
    try:
        if df is None:
            return fallback_df
        clean = df.copy()
        for col in ["WORD / PHRASE", "COMMENT"]:
            if col not in clean.columns:
                clean[col] = ""
        clean = clean[["WORD / PHRASE", "COMMENT"]]
        clean["WORD / PHRASE"] = clean["WORD / PHRASE"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()
        clean["COMMENT"] = clean["COMMENT"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()
        clean = clean[clean["WORD / PHRASE"] != ""]
        return clean.reset_index(drop=True)
    except Exception:
        return fallback_df


def append_word_rows(existing_df, new_rows_df):
    if existing_df is None or existing_df.empty:
        combined = new_rows_df.copy()
    else:
        combined = pd.concat([existing_df, new_rows_df], ignore_index=True)
    combined["WORD / PHRASE"] = combined["WORD / PHRASE"].astype(str)
    combined["COMMENT"] = combined["COMMENT"].astype(str)
    return combined.reset_index(drop=True)


# ============================================================
# UI
# ============================================================

st.title("📑 PDF Highlighter")
st.info(
    """
**How to use this tool:**
1. **Upload a PDF** below.
2. **Add words/phrases to highlight** — paste a column straight from a spreadsheet (one word per line), or two
   columns (word + comment) copied together, or just type/paste directly into the table.
3. Click **Generate Highlighted PDF** to download `YOURFILE_HIGHLIGHTED.pdf`.
"""
)

st.divider()

st.subheader("1. Upload PDF")
uploaded_pdf = st.file_uploader(
    "Upload the PDF you want to review",
    type=["pdf"],
    key=f"pdf_uploader_{st.session_state.uploader_key}",
)

st.divider()

st.subheader("2. Words / Phrases to Highlight")

top1, top2 = st.columns([1, 3])
with top1:
    with st.popover("📋 Paste from Spreadsheet", use_container_width=True):
        st.caption(
            "Copy a column of words from Excel/Sheets and paste it here (one per line). "
            "If you copy two columns (word + comment) together, both will be used."
        )
        paste_text = st.text_area("Paste here", height=150, key="txt_paste_words", label_visibility="collapsed")
        if st.button("Add to Table", key="btn_paste_words", use_container_width=True):
            if not paste_text.strip():
                st.warning("Paste some words first.")
            else:
                parsed_df = parse_pasted_words(paste_text)
                if parsed_df.empty:
                    st.warning("Couldn't find any words in that paste.")
                else:
                    st.session_state.word_data = append_word_rows(st.session_state.word_data, parsed_df)
                    st.rerun()
with top2:
    st.caption(
        "Or click any cell in the grid below to type/paste directly. "
        "Leave COMMENT blank to use an auto-generated note."
    )

_column_config = {
    "WORD / PHRASE": st.column_config.TextColumn("WORD / PHRASE", required=True, width="medium"),
    "COMMENT": st.column_config.TextColumn("COMMENT", width="large", help="Note attached to the highlight"),
}

try:
    edited_words = st.data_editor(
        st.session_state.word_data,
        column_config=_column_config,
        num_rows="dynamic",
        use_container_width=True,
        height=300,
        key="editor_words",
    )
    st.session_state.word_data = sanitize_word_df(edited_words, st.session_state.word_data)
except Exception as e:
    st.error(f"Couldn't apply that edit/paste, so it was ignored: {e}")

if st.button("🗑️ Clear Words", key="clr_words"):
    st.session_state.word_data = pd.DataFrame(columns=["WORD / PHRASE", "COMMENT"])
    st.rerun()

st.divider()

st.subheader("3. Generate")

word_df = st.session_state.word_data
word_map = build_word_map(word_df)

if uploaded_pdf is None:
    st.warning("Upload a PDF above to continue.")
elif not word_map:
    st.warning("Add at least one word/phrase to highlight.")
else:
    if st.button("✨ Generate Highlighted PDF", type="primary", use_container_width=True):
        try:
            with st.spinner("Scanning PDF and applying highlights..."):
                input_bytes = uploaded_pdf.getvalue()
                output_bytes, match_counts = highlight_words_in_pdf(input_bytes, word_map)

            zero_hits = [w for w, c in match_counts.items() if c == 0]
            total_hits = sum(match_counts.values())

            st.success(f"Done! {total_hits} total highlight(s) applied across {len(word_map)} word(s)/phrase(s).")

            with st.expander("Match details"):
                for w, c in match_counts.items():
                    st.write(f"• **{w}** → {c} match(es)")

            if zero_hits:
                st.warning(
                    "No matches found for: " + ", ".join(f"'{w}'" for w in zero_hits) +
                    ". Check spelling/case, or the PDF may not contain selectable text for these."
                )

            filename, _ext = os.path.splitext(uploaded_pdf.name)
            out_name = f"{filename}_HIGHLIGHTED.pdf"

            st.download_button(
                label="📄 Download Highlighted PDF",
                data=output_bytes,
                file_name=out_name,
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Highlighting failed: {type(e).__name__}: {e}")
            with st.expander("Show detailed error logs"):
                st.code(traceback.format_exc())
