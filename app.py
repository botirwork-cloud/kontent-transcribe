import os
import io
import time
import base64
import tempfile
import subprocess
from dotenv import load_dotenv
import streamlit as st
from google import genai
from docx import Document

# Созламалар
load_dotenv()

GEMINI_API_KEY = (
    st.secrets.get("GEMINI_API_KEY") 
    if "GEMINI_API_KEY" in getattr(st, "secrets", {}) 
    else os.getenv("GEMINI_API_KEY")
)

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

st.set_page_config(
    page_title="Kontent Markazi - transcription",
    page_icon="🎙",
    layout="centered"
)

# Видео логотипни хотирада кэшлаш (қотиб қолишни тўхтатади)
@st.cache_data
def get_video_html(video_path):
    if os.path.exists(video_path):
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        b64 = base64.b64encode(video_bytes).decode()
        return f"""
        <div style="text-align: center; margin-bottom: 10px;">
            <video width="100%" style="max-width: 520px; border-radius: 12px;" autoplay muted playsinline onended="this.pause();">
                <source src="data:video/mp4;base64,{b64}" type="video/mp4">
            </video>
        </div>
        """
    return ""

# 1. Логотип видеоси
logo_html = get_video_html("video.mp4")
if logo_html:
    st.markdown(logo_html, unsafe_allow_html=True)

# 2. Сарлавҳа ва корпоратив матнлар
st.markdown("<h2 style='text-align: center; margin-top: 0;'>Audio va video transkripsiya</h2>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align: center; color: #4A90E2; font-weight: 600; margin-bottom: 5px;'>"
    "Dastur muallifi: Botir Gʻofurov</p>", 
    unsafe_allow_html=True
)
st.info(
    "Ushbu dastur oʻzbek, rus va ingliz tilidagi audio hamda video fayllarni matnga aylantirib beradi. "
    "Mazkur korporativ dasturdan Kontent markazi xodimlari foydalanishi mumkin."
)

# 3. Файл юклаш
uploaded_file = st.file_uploader(
    "Video yoki audio faylni yuklang:",
    type=["mp3", "wav", "m4a", "ogg", "mp4", "mkv", "avi", "mov"]
)

if uploaded_file is not None:
    st.success(f"Fayl tanlandi: **{uploaded_file.name}** ({uploaded_file.size / (1024*1024):.1f} MB)")
    
    st.subheader("Sozlamalar")
    lang_choice = st.radio(
        "Transkripsiya tilini tanlang:",
        options=["Oʻzbek", "Rus", "Ingliz"],
        horizontal=True
    )

    script_choice = None
    if lang_choice == "Oʻzbek":
        script_choice = st.radio(
            "Matn qaysi alifboda boʻlsin?:",
            options=["Lotin", "Кирилл"],
            horizontal=True
        )

    col1, col2 = st.columns([1, 1])
    with col1:
        start_button = st.button("▶️ Ishni boshlash", type="primary", use_container_width=True)
    with col2:
        cancel_button = st.button("❌ Bekor qilish", use_container_width=True)

    if cancel_button:
        st.warning("Amaliyot bekor qilindi.")
        st.rerun()

    if start_button:
        file_suffix = os.path.splitext(uploaded_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as tmp_file:
            tmp_file.write(uploaded_file.read())
            temp_input_path = tmp_file.name

        audio_path = temp_input_path
        temp_extracted_audio = None
        uploaded_cloud_file = None
        transcribed_text = ""

        with st.status("Ishlanmoqda, iltimos kuting...", expanded=True) as status:
            try:
                # 4.1. Видео бўлса аудио ажратиш
                video_extensions = [".mp4", ".mkv", ".avi", ".mov"]
                if file_suffix in video_extensions:
                    status.update(label="🎬 Videodan audio ajratilmoqda...")
                    temp_extracted_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
                    cmd = [
                        "ffmpeg", "-y", "-i", temp_input_path,
                        "-vn", "-acodec", "libmp3lame", "-q:a", "4", temp_extracted_audio
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    audio_path = temp_extracted_audio

                status.update(label="✨ Audio serverga yuklanmoqda...")
                uploaded_cloud_file = gemini_client.files.upload(file=audio_path)

                # Файл булутда ACTIVE бўлишини кутиш
                status.update(label="⏳ Fayl tahlilga tayyorlanmoqda...")
                while uploaded_cloud_file.state.name == "PROCESSING":
                    time.sleep(2)
                    uploaded_cloud_file = gemini_client.files.get(name=uploaded_cloud_file.name)

                if uploaded_cloud_file.state.name != "ACTIVE":
                    raise Exception("Faylni yuklashda xatolik yuz berdi.")

                # Prompt
                if lang_choice == "Oʻzbek":
                    script_prompt = (
                        "Matnni faqat LOTIN alifbosida yozing." 
                        if script_choice == "Lotin" 
                        else "Матнни фақат КИРИЛЛ алифбосида ёзинг."
                    )
                    prompt = (
                        f"Ушбу аудиодаги ўзбекча нутқни сўзма-сўз аниқ матнга (транскрипция) айлантириб бер. "
                        f"{script_prompt} Имло қоидаларига қатъий амал қил. "
                        f"Ортиқча кириш ва якуний гапларсиз, фақат матнни қайтар."
                    )
                elif lang_choice == "Rus":
                    prompt = (
                        "Сделай максимально точную транскрипцию русской речи из этого аудио. "
                        "Строго соблюдай правила русской орфографии и пунктуации. "
                        "ОСОБОЕ ВНИМАНИЕ: названия зарубежных компаний, брендов, сервисов, имена собственные "
                        "и термины нерусского происхождения пиши на языке оригинала в латинице (например: Google, YouTube, Telegram, Zoom, iPhone). "
                        "Выведи только полученный текст без лишних вступительных слов и комментариев."
                    )
                else:  # Ingliz
                    prompt = (
                        "Transcribe the spoken English in this audio verbatim with high accuracy. "
                        "Ensure correct spelling, capitalization, and punctuation. "
                        "Output only the transcribed text without any greetings or additional comments."
                    )

                status.update(label="🧠 Matn tahlil qilinmoqda va imlo tekshirilmoqda...")
                gemini_response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[uploaded_cloud_file, prompt]
                )
                transcribed_text = gemini_response.text

                status.update(label="✅ Jarayon yakunlandi. Matn tayyor!", state="complete", expanded=False)

            except Exception as e:
                status.update(label="❌ Xatolik yuz berdi", state="error")
                st.error(f"Xatolik tafsiloti: {str(e)}")

            finally:
                if uploaded_cloud_file:
                    try:
                        gemini_client.files.delete(name=uploaded_cloud_file.name)
                    except Exception:
                        pass
                for p in [temp_input_path, temp_extracted_audio]:
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

        if transcribed_text:
            st.success("✅ Matn tayyor boʻldi!")
            st.text_area(
                label="Transkripsiya qilingan matn (uni tahrir qilishingiz yoki nusxalab olishingiz mumkin):",
                value=transcribed_text,
                height=350
            )

            doc = Document()
            for paragraph in transcribed_text.split("\n"):
                if paragraph.strip():
                    doc.add_paragraph(paragraph)

            docx_buffer = io.BytesIO()
            doc.save(docx_buffer)
            docx_buffer.seek(0)

            st.download_button(
                label="📄 Word (.docx) yuklab olish",
                data=docx_buffer,
                file_name="transcription.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True
            )
