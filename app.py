import os
import base64
import tempfile
import subprocess
from dotenv import load_dotenv
import streamlit as st
from google import genai

# Созламалар
load_dotenv()

# Калитни аввал Streamlit Secrets'дан, агар у ерда бўлмаса .env дан қидиради
GEMINI_API_KEY = (
    st.secrets.get("GEMINI_API_KEY") 
    if "GEMINI_API_KEY" in getattr(st, "secrets", {}) 
    else os.getenv("GEMINI_API_KEY")
)

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

st.set_page_config(
    page_title="Kontent Markazi - Транскрипция",
    page_icon="🎙",
    layout="centered"
)

# Видео логотипни база64 га айлантириб, браузерда тўғри кўрсатиш
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

# 1. Логотип видеосини чиқариш (video.mp4 шу папкада бўлиши керак)
logo_html = get_video_html("video.mp4")
if logo_html:
    st.markdown(logo_html, unsafe_allow_html=True)

# 2. Сарлавҳа ва корпоратив матнлар
st.markdown("<h2 style='text-align: center; margin-top: 0;'>Аудио ва Видео Транскрипция</h2>", unsafe_allow_html=True)
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
    "Видео ёки аудио файлни юкланг:",
    type=["mp3", "wav", "m4a", "ogg", "mp4", "mkv", "avi", "mov"]
)

if uploaded_file is not None:
    st.success(f"Файл танланди: **{uploaded_file.name}** ({uploaded_file.size / (1024*1024):.1f} MB)")
    
    st.subheader("Созламалар")
    lang_choice = st.radio(
        "Транскрипция тилини танланг:",
        options=["Ўзбек", "Рус", "Инглиз"],
        horizontal=True
    )

    script_choice = None
    if lang_choice == "Ўзбек":
        script_choice = st.radio(
            "Алифбони танланг:",
            options=["Лотин", "Кирилл"],
            horizontal=True
        )

    col1, col2 = st.columns([1, 1])
    with col1:
        start_button = st.button("▶️ Ишни бошлаш", type="primary", use_container_width=True)
    with col2:
        cancel_button = st.button("❌ Бекор қилиш", use_container_width=True)

    if cancel_button:
        st.warning("Амалиёт бекор қилинди.")
        st.rerun()

    if start_button:
        with st.status("Жараён кетмоқда...", expanded=True) as status:
            file_suffix = os.path.splitext(uploaded_file.name)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as tmp_file:
                tmp_file.write(uploaded_file.read())
                temp_input_path = tmp_file.name

            audio_path = temp_input_path
            temp_extracted_audio = None
            uploaded_cloud_file = None

            try:
                # Видео бўлса, FFmpeg орқали аудио ажратиб олиш
                video_extensions = [".mp4", ".mkv", ".avi", ".mov"]
                if file_suffix in video_extensions:
                    status.update(label="🎬 Видеодан аудио ажратилмоқда (FFmpeg)...")
                    temp_extracted_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
                    cmd = [
                        "ffmpeg", "-y", "-i", temp_input_path,
                        "-vn", "-acodec", "libmp3lame", "-q:a", "4", temp_extracted_audio
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    audio_path = temp_extracted_audio

                status.update(label="✨ Аудио Gemini сунъий интеллект тизимига юкланмоқда...")
                uploaded_cloud_file = gemini_client.files.upload(file=audio_path)

                # Тил ва имло бўйича аниқ кўрсатма (Prompt)
                if lang_choice == "Ўзбек":
                    script_prompt = (
                        "Matnni faqat LOTIN alifbosida yozing." 
                        if script_choice == "Лотин" 
                        else "Матнни фақат КИРИЛЛ алифбосида ёзинг."
                    )
                    prompt = (
                        f"Ушбу аудиодаги ўзбекча нутқни сўзма-сўз аниқ матнга (транскрипция) айлантириб бер. "
                        f"{script_prompt} Имло қоидаларига қатъий амал қил. "
                        f"Ортиқча кириш ва якуний гапларсиз, фақат матнни қайтар."
                    )
                elif lang_choice == "Рус":
                    prompt = (
                        "Сделай максимально точную транскрипцию русской речи из этого аудио. "
                        "Строго соблюдай правила русской орфографии и пунктуации. "
                        "ОСОБОЕ ВНИМАНИЕ: названия зарубежных компаний, брендов, сервисов, имена собственные "
                        "и термины нерусского происхождения пиши на языке оригинала в латинице (например: Google, YouTube, Telegram, Zoom, iPhone). "
                        "Выведи только полученный текст без лишних вступительных слов и комментариев."
                    )
                else:  # Инглиз
                    prompt = (
                        "Transcribe the spoken English in this audio verbatim with high accuracy. "
                        "Ensure correct spelling, capitalization, and punctuation. "
                        "Output only the transcribed text without any greetings or additional comments."
                    )

                status.update(label="🧠 Нутқ таҳлил қилинмоқда ва имло тўғриланмоқда...")
                gemini_response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[uploaded_cloud_file, prompt]
                )
                transcribed_text = gemini_response.text

                status.update(label="✅ Муваффақиятли тайёр бўлди!", state="complete", expanded=False)

                st.subheader("📝 Транскрипция матни:")
                st.text_area("Матн майдони:", value=transcribed_text, height=350)

                st.download_button(
                    label="💾 Матнни юклаб олиш (.txt)",
                    data=transcribed_text,
                    file_name="transcription.txt",
                    mime="text/plain",
                    use_container_width=True
                )

            except Exception as e:
                status.update(label="❌ Хатолик юз берди", state="error")
                st.error(f"Хатолик тафсилоти: {str(e)}")

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
