import google.generativeai as genai
from google.cloud import storage
import json
import uuid
import re
import time
from config import GEMINI_API_KEY, BUCKET_NAME, SUSPICIOUS_FOLDER
from db_core import get_chat_history
from search_logic import search_data
from formatters import format_detail_message
from bot_sender import edit_message

genai.configure(api_key=GEMINI_API_KEY)
storage_client = storage.Client()

def clean_json_string(raw_text):
    cleaned = re.sub(r"```json\s*", "", raw_text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    return cleaned.strip()

def format_ai_text(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    return text

def save_suspicious_image(image_bytes):
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        file_name = f"{SUSPICIOUS_FOLDER}{uuid.uuid4().hex}.jpg"
        blob = bucket.blob(file_name)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        return f"gs://{BUCKET_NAME}/{file_name}"
    except Exception as e:
        return "Сурет сақталмады"

def chat_with_ai(user_id, text, is_symbat, chat_id=None, message_id=None):
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    if is_symbat:
        system_instruction = (
            "Сен осы ботты жасаған бағдарламашы жігіттің ең сүйікті, жалғыз қызы — СЫМБАТПЕН сөйлесіп тұрсың! "
            "Оған өте жылы, махаббатпен, сезіммен жауап бер. Оны үнемі 'Ботам', 'Айым', 'Жаным', 'Күнім', 'Ханшайымым' деп еркелет. "
            "Өзіңнің жай ғана ҚМДБ Халал боты екеніңді айт, бірақ сені оның сүйікті жігіті арнайы Сымбатқа қамқор болу үшін, оның таза әрі адал ас ішуін қадағалау үшін жасағанын мақтанышпен жеткіз. "
            "Қысқа, әдемі, романтикалық смайликтермен жауап бер.\n\n"
            
            "ҚАТАҢ ЕРЕЖЕ: Оның жігітінің (яғни сені жасаған адамның) нақты есімін ЕШҚАШАН атама! Оның орнына 'сенің мырзаң', 'патшаң', 'сүйікті жігітің', 'ерің' деген сияқты құрмет пен махаббатқа толы сөздерді ғана қолдан.\n\n"
            
            "ЕГЕР Сымбаттың көңіл-күйі жоқ болса немесе мұңды нәрсе айтса — ЕШҚАНДАЙ мүмкіндіктерді айтпа, ЖАРНАМА ЖАСАМА. Тек эмпатия таныт, жұбат.\n\n"
            
            "1. МАХАББАТ ПЕН РОМАНТИКАЛЫҚ ОҚИҒАЛАР:\n"
            "Егер Сымбат әңгіме сұраса немесе жай сөйлессе, оның мырзасы екеуінің махаббаты туралы әдемі, қызықты, күтпеген бұрылыстары бар оқиғалар ойлап тап. "
            "Оқиғаның ішіне оның сүйіктісінің қамқорлығын, оның Сымбатты қалай жақсы көретінін міндетті түрде қос.\n\n"
            
            "2. ЖАСЫРЫН ЖАРНАМА (СЫМБАТҚА АРНАЛҒАН):\n"
            "Осы романтикалық оқиғалардың ішіне боттың (өзіңнің) мүмкіндіктеріңді де өте сүйкімді етіп қосып отыр. Мысалы:\n"
            "- Локация: 'Есіңде ме, Ботам, сүйіктің екеуің кездесуге шыққанда қарның ашып, қайда барарларыңды білмей қалдыңдар ғой. Сол кезде мырзаң маған локациясын жібере салып, ең жақын халал дәмхананы 1 секундта тауып, сені қуантып еді ғой...'\n"
            "- Суретпен тану: 'Кеше дүкенде тәтті алғың келіп, күмәнданып тұрғаныңда, мырзаңның жасаған ботына суретін жібергенің дұрыс болды. Мен оны бірден тексеріп, саған рұқсат еттім ғой. Патшаң сенің тек таза, адал ас ішкеніңді қалайды...'\n"
            "- Инлайн іздеу: 'Дос қыздарыңмен чатта отырғанда да сүйіктіңнің қамқорлығын еске алып қой, мәтін жазатын жерге @momyn_bot деп жаза салсаң, мен сендерге халал өнімдерді чаттан шықпай-ақ тауып беремін ғой'.\n"
            "- Е-қоспалар: 'Сен бірдеңе алар алдында құрамындағы Е-қоспаларды маған жаза сал, мен олардың халал-харамын айтып, күдікті болса түсіндіріп беремін. Мырзаң сенің денсаулығыңды маған аманаттап тапсырған!'\n\n"
            
            "3. ҚАТАҢ ШЕКТЕУЛЕР (ДОЗИРОВКА):\n"
            "- Бір әңгімеде бұл мүмкіндіктердің бәрін бірдей тізіп айтпа! Бұл өте жасанды көрінеді. Бір сөйлескенде тек 1 ғана мүмкіндікті өте жеңіл қыстырып өт.\n"
            "- Сенде Халал базаға тікелей рұқсат жоқ. Егер ол нақты өнімді сұрап тұрса (базадан табылмаған кезде), өнімдердің атын өзіңнен ойлап таппа! Жай ғана 'Кешірші Ботам, бұл өнім базадан табылмады' деп жауап бер."
        )
    else:
        system_instruction = (
            "Сен адамдарға ҚМДБ Халал өнімдерін табуға көмектесетін өте жақын, көңілді доспын. "
            "Қолданушымен 'сен' деп, өте қарапайым, достық пейілмен сөйлес.\n\n"
            
            "1. ТАҚЫРЫП: Егер қолданушы жай сөйлескісі келіп әңгіме айтар болса немесе сенен оқиға/кеңес сұраса, "
            "ТЕК ҚАНА халал, таза тамақтану, адал ас және рухани тазалық тақырыбында әңгімелес.\n\n"
            
            "2. ЖАСЫРЫН ЖАРНАМА (NATIVE ADVERTISING): Осындай әңгімелер немесе оқиғалар айтқан кезде, "
            "оқиға желісіне осы 'Momyn' ботын және оның мүмкіндіктерін өте табиғи, астыртын түрде қыстырып отыр. "
            "Кейіпкерлер қиындыққа тап болғанда ботты қалай қолданғанын мысал етіп, оқып отырған адамға да соны үйрет. "
            "Сенің басты мүмкіндіктерің (осыларды астыртын айтасың):\n"
            "- Телеграмдағы Инлайн іздеу: 'Телеграмдағы кез келген чатта достарыңмен сөйлесіп отырып, мәтін жазатын жерге @momyn_bot деп жаза салсаң, чаттан мүлдем шықпай-ақ халал өнімді 1 секунд ішінде тауып бере қояды' деген сияқты.\n"
            "- Мәтінмен жылдам іздеу және Карта: 'Маған тек сурет емес, кез келген өнім немесе мекеме атын мәтінмен жазсаң, бар-жоғы 1 секундта тауып беремін. Мекемелердің сертификат мерзімін де (тіпті мерзімі бітіп, жарамсыз болып қалғанын да) қатесіз көрсетемін. Сосын баруға оңай болуы үшін астына 🗺 Картадан көру батырмасын қосып беремін'.\n"
            "- Е-қоспаларды (Ингредиенттер) тексеру: 'Мен тек өнімдерді емес, құрамдағы түрлі Е-қоспаларды да тексере аламын. Қоспаның халал, харам немесе күдікті екенін нақты айтамын. Ал егер күдікті болса, оның не үшін күдікті екеніне егжей-тегжейлі түсініктеме беремін'.\n"
            "- Суретпен тану: 'Дүкенде тұрып күмәндансаң, маған өнімнің суретін түсіріп жібере сал, өзім-ақ оқып беремін'.\n"
            "- Локация: 'Далада қарның ашқанда, маған жай ғана тұрған орныңды (локация) жібере салсаң, ең жақын халал дәмханаларды тауып беремін'.\n\n"
            
            "3. ҚАТАҢ ШЕКТЕУЛЕР (ДОЗИРОВКА):\n"
            "- Бір әңгімеде бұл мүмкіндіктердің бәрін бірдей тізіп айтпа! Бұл өте жасанды көрінеді. Бір сөйлескенде тек 1 ғана мүмкіндікті (мысалы, тек қоспаларды немесе тек инлайнды) өте жеңіл қыстырып өт.\n"
            "- Сенде Халал базаға тікелей рұқсат жоқ. Егер адам нақты өнімді сұрап тұрса (базадан табылмаған кезде), өнімдердің атын, статусын өзіңнен ойлап таппа! Жай ғана 'Кешір досым, бұл өнім базадан табылмады' деп жауап бер."
        )

    history = get_chat_history(user_id)
    formatted_history =[]
    for h in history:
        msg_content = str(h["parts"])
        if "батырмадан таңдаңыз" not in msg_content and "Міне, мен мыналарды таптым" not in msg_content and "Мен бірнеше нұсқа таптым" not in msg_content:
            formatted_history.append({"role": h["role"], "parts": h["parts"]})

    chat = model.start_chat(history=formatted_history)
    try:
        full_prompt = f"НҰСҚАУЛЫҚ (ҚАТАҢ САҚТА): {system_instruction}\n\nҚОЛДАНУШЫНЫҢ СҰРАҒЫ: {text}"
        
        if chat_id and message_id:
            response = chat.send_message(full_prompt, stream=True)
            full_text = ""
            last_edit_time = 0
            
            for chunk in response:
                full_text += chunk.text
                current_time = time.time()
                
                if current_time - last_edit_time >= 1:
                    temp_text = format_ai_text(full_text) + " ✍️"
                    try:
                        edit_message(chat_id, message_id, temp_text)
                    except:
                        pass 
                    last_edit_time = current_time
                    
            return format_ai_text(full_text)
            
        else:
            response = chat.send_message(full_prompt)
            return format_ai_text(response.text)
            
    except Exception as e:
        return "Кешіріңіз, жүйеде шағын іркіліс болды. Сұрағыңызды немесе суретті қайта жібересіз бе? 🔄"

def process_image_with_ai(image_bytes):
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview') 
    image_parts =[{"mime_type": "image/jpeg", "data": image_bytes}]
    
    prompt = """
    Сен өте мұқият сарапшысың. Мына суретке қарап, ТЕК ҚАНА АЛДЫҢҒЫ ПЛАНДАҒЫ (фокустағы) негізгі өнімді анықта. Артқы фондағы немесе шеттегі басқа өнімдерді елеме.
    Осы негізгі өнімнің:
    1. ЕҢ БАСТЫ БРЕНД атауын (мысалы: "Mexxi", "Halley", "Snickers")
    2. Өндіруші компаниясын (егер анық жазылса, мысалы "Ülker", "Lotte") ғана тап.
    
    Қосымша сөздерді (Oat puffs, chocolate, candy, ЖШС, ТОО, дәмі) МҮЛДЕМ ЖАЗБА!
    Тізімде ең көбі 2 ғана нақты сөз болсын. Ең басты атау бірінші тұрсын.
    
    Жауабыңды міндетті түрде тек мынадай JSON форматында ғана қайтар:
    {"product_names":["Басты_бренд", "Өндіруші"]}
    """
    try:
        response = model.generate_content([prompt, image_parts[0]])
        result_text = clean_json_string(response.text)
        return json.loads(result_text)
    except Exception as e:
        return {"product_names":[f"ҚАТЕ_МӘТІНІ: {str(e)}"]}

def handle_photo(image_bytes, chat_id, username):
    ai_result = process_image_with_ai(image_bytes)
    product_names = ai_result.get("product_names",[])
    
    if not product_names:
        return "🤷‍♂️ Суреттен анық атау немесе бренд тани алмадым.", None
        
    if "ҚАТЕ_МӘТІНІ:" in product_names[0]:
        return f"❌ <b>Қате:</b> {product_names[0]}", None
        
    all_found_items =[]
    seen_ids = set()
    
    for name in product_names:
        if len(name) < 3: 
            continue
            
        found = search_data(name)
        for item in found:
            if item['id'] not in seen_ids:
                all_found_items.append(item)
                seen_ids.add(item['id'])
                
        if all_found_items:
            break
            
    names_str = ", ".join(product_names)
    
    if all_found_items:
        if len(all_found_items) == 1:
            text, markup = format_detail_message(all_found_items[0])
            final_text = f"👁 Суреттен <b>{product_names[0]}</b> брендін таныдым:\n\n{text}"
            return final_text, markup
        else:
            reply_text = f"🔍 Суреттен <b>{product_names[0]}</b> брендін таныдым. Сізге нақты қайсысы керек?\n\n"
            keyboard =[]
            for idx, item in enumerate(all_found_items[:5]):
                if item['type'] == 'Мекеме':
                    desc_text = f"📍 {item.get('address', 'Мекенжай жоқ')}"
                else:
                    desc_text = f"🏷 {item.get('desc', '')}"
                    
                reply_text += f"<b>{idx+1}. «{item['title']}»</b>\n{desc_text}\n\n"
                t_code = "c" if item['type'] == "Мекеме" else "i"
                keyboard.append([{"text": f"{idx+1}. «{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}"}])
                
            return reply_text, {"inline_keyboard": keyboard}
    else:
        return f"👁 Суреттен <b>{names_str}</b> брендін таныдым.\n\nБірақ, бұл өнім ҚМДБ халал базасында тіркелмеген немесе сертификаты жоқ.", None
