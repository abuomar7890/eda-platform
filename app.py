import streamlit as st
from supabase import create_client, Client
import socket
import uuid

st.set_page_config(page_title="EDA Platform", page_icon="📊", layout="wide")

# --- تهيئة الاتصال بـ Supabase ---
@st.cache_resource
def init_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

try:
    supabase: Client = init_supabase()
except Exception:
    st.error("تعذر الاتصال بـ Supabase. تحقق من رابط المشروع ومفتاح API في secrets.toml.")
    st.stop()

# --- إدارة حالة الجلسة ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = None
if 'user_id' not in st.session_state:
    st.session_state.user_id = None

# --- دوال المصادقة ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.logged_in = True
        st.session_state.user_email = email
        user_data = supabase.auth.get_user()
        if user_data.user:
            st.session_state.user_id = user_data.user.id
        st.success("تم تسجيل الدخول بنجاح!")
        st.rerun()
    except socket.gaierror:
        st.error("تعذر الوصول إلى خادم Supabase.")
    except Exception as e:
        st.error(f"خطأ في تسجيل الدخول: {e}")

def signup(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        st.success("تم إنشاء الحساب بنجاح!")
    except socket.gaierror:
        st.error("تعذر الوصول إلى خادم Supabase.")
    except Exception as e:
        st.error(f"خطأ: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.logged_in = False
    st.session_state.user_email = None
    st.session_state.user_id = None
    st.rerun()

# --- دوال مساعدة ---
def get_correct_mime_type(file_name):
    extension = file_name.split('.')[-1].lower()
    mime_types = {
        'csv': 'text/csv',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'json': 'application/json',
        'tsv': 'text/tab-separated-values',
        'parquet': 'application/octet-stream'
    }
    return mime_types.get(extension, 'application/octet-stream')

def validate_file(uploaded_file):
    MAX_SIZE_MB = 10
    file_size_mb = uploaded_file.size / (1024 * 1024)
    
    if file_size_mb > MAX_SIZE_MB:
        return False, f"حجم الملف كبير جداً ({file_size_mb:.2f} ميجابايت)."
    
    allowed_extensions = ['csv', 'xls', 'xlsx', 'json', 'tsv', 'parquet']
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    if file_extension not in allowed_extensions:
        return False, f"امتداد الملف غير مدعوم ({file_extension})."
    
    return True, None

# --- دوال Storage ---
def upload_file_to_storage(uploaded_file, file_path):
    try:
        file_bytes = uploaded_file.read()
        correct_mime_type = get_correct_mime_type(uploaded_file.name)
        
        response = supabase.storage.from_('eda-uploads').upload(
            file_path,
            file_bytes,
            file_options={"content_type": correct_mime_type}
        )
        
        return True, response
    except Exception as e:
        return False, str(e)

def save_file_metadata(user_id, email, file_name, file_size, file_type, file_path):
    try:
        data = {
            "user_id": user_id,
            "email": email,
            "file_name": file_name,
            "file_size": file_size,
            "file_type": file_type,
            "file_path": file_path
        }
        
        result = supabase.table("files").insert(data).execute()
        return True, result
    except Exception as e:
        return False, str(e)

def get_user_files(user_id):
    """جلب ملفات المستخدم من قاعدة البيانات"""
    try:
        result = supabase.table("files").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return result.data
    except Exception as e:
        st.error(f"خطأ في جلب الملفات: {e}")
        return []

def delete_file(file_id, file_path):
    """حذف ملف من Storage و Database - الآن سيعمل بعد إضافة سياسة DELETE"""
    errors = []
    
    # 1. حذف من Storage
    try:
        supabase.storage.from_('eda-uploads').remove([file_path])
    except Exception as e:
        errors.append(f"Storage: {str(e)}")
    
    # 2. حذف من Database (الآن سيعمل مع سياسة DELETE)
    try:
        result = supabase.table("files").delete().eq("id", file_id).execute()
        # التحقق من نجاح الحذف
        if hasattr(result, 'error') and result.error:
            errors.append(f"Database: {result.error.message}")
    except Exception as e:
        errors.append(f"Database: {str(e)}")
    
    return len(errors) == 0, errors

def download_file(file_path):
    """تحميل ملف من Storage"""
    try:
        response = supabase.storage.from_('eda-uploads').download(file_path)
        return response
    except Exception as e:
        return None

# --- واجهة المستخدم ---
def main():
    if st.session_state.logged_in:
        st.title(f"مرحباً بك، {st.session_state.user_email} ")
        
        tab_home, tab_upload, tab_files = st.tabs(["🏠 الرئيسية", "📤 رفع الملفات", "📁 ملفاتي"])
        
        # === التبويب الرئيسي ===
        with tab_home:
            st.write("أنت الآن في الصفحة الرئيسية لمنصة التحليل الاستكشافي.")
            st.write("⚠️ المشروع قيد التطوير، سيتم إضافة صفحات التحليل قريباً!")
            
            if st.button("تسجيل الخروج"):
                logout()
        
        # === تبويب رفع الملفات ===
        with tab_upload:
            st.subheader("📤 رفع ملف بيانات جديد")
            
            st.info("""
            **الأنواع المسموحة:**
            - CSV (.csv)
            - Excel (.xls, .xlsx)
            - JSON (.json)
            - TSV (.tsv)
            - Parquet (.parquet)
            
            **الحد الأقصى للحجم:** 10 ميجابايت
            """)
            
            uploaded_file = st.file_uploader(
                "اختر ملفاً للرفع",
                type=['csv', 'xls', 'xlsx', 'json', 'tsv', 'parquet'],
                help="اختر ملف البيانات الذي تريد تحليله"
            )
            
            if uploaded_file is not None:
                st.write("**معلومات الملف:**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("اسم الملف", uploaded_file.name)
                with col2:
                    size_mb = uploaded_file.size / (1024 * 1024)
                    st.metric("الحجم", f"{size_mb:.2f} ميجابايت")
                with col3:
                    ext = uploaded_file.name.split('.')[-1].upper()
                    st.metric("النوع", ext)
                
                if st.button("🚀 رفع الملف", type="primary"):
                    with st.spinner("جاري رفع الملف..."):
                        is_valid, error_msg = validate_file(uploaded_file)
                        
                        if not is_valid:
                            st.error(f"❌ {error_msg}")
                        else:
                            file_extension = uploaded_file.name.split('.')[-1].lower()
                            unique_filename = f"{st.session_state.user_id}/{uuid.uuid4()}.{file_extension}"
                            
                            success, result = upload_file_to_storage(uploaded_file, unique_filename)
                            
                            if success:
                                correct_type = get_correct_mime_type(uploaded_file.name)
                                
                                meta_success, meta_result = save_file_metadata(
                                    user_id=st.session_state.user_id,
                                    email=st.session_state.user_email,
                                    file_name=uploaded_file.name,
                                    file_size=uploaded_file.size,
                                    file_type=correct_type,
                                    file_path=unique_filename
                                )
                                
                                if meta_success:
                                    st.success("✅ تم رفع الملف بنجاح!")
                                    st.balloons()
                                else:
                                    st.warning(f"⚠️ تم رفع الملف ولكن فشل حفظ البيانات: {meta_result}")
                            else:
                                st.error(f"❌ فشل رفع الملف: {result}")
        
        # === تبويب ملفاتي ===
        with tab_files:
            st.subheader("📁 ملفاتي المرفوعة")
            
            # زر تحديث القائمة
            if st.button("🔄 تحديث القائمة"):
                st.rerun()
            
            # جلب ملفات المستخدم
            user_files = get_user_files(st.session_state.user_id)
            
            if len(user_files) == 0:
                st.info("📭 لا توجد ملفات مرفوعة. اذهب إلى تبويب 'رفع الملفات' لرفع ملفك الأول!")
            else:
                st.success(f"✅ لديك {len(user_files)} ملف(ات)")
                st.markdown("---")
                
                # عرض الملفات
                for file in user_files:
                    with st.container():
                        col_name, col_size, col_date, col_actions = st.columns([3, 1, 1, 2])
                        
                        with col_name:
                            st.write(f"**📄 {file['file_name']}**")
                            st.caption(f"النوع: {file['file_type']}")
                        
                        with col_size:
                            size_mb = file['file_size'] / (1024 * 1024)
                            st.write(f"**الحجم:**")
                            st.caption(f"{size_mb:.2f} MB")
                        
                        with col_date:
                            st.write(f"**التاريخ:**")
                            created_at = file['created_at'][:10] if file['created_at'] else 'غير معروف'
                            st.caption(created_at)
                        
                        with col_actions:
                            # زر التحميل
                            if st.button("📥 تحميل", key=f"dl_{file['id']}", use_container_width=True):
                                with st.spinner("جاري التحميل..."):
                                    file_data = download_file(file['file_path'])
                                    if file_data:
                                        st.download_button(
                                            label="⬇️ اضغط للتحميل",
                                            data=file_data,
                                            file_name=file['file_name'],
                                            mime=file['file_type'],
                                            key=f"dl_confirm_{file['id']}"
                                        )
                                    else:
                                        st.error("⚠️ الملف غير موجود في التخزين")
                            
                            # زر الحذف - الآن سيعمل بعد إضافة سياسة DELETE
                            if st.button("🗑️ حذف", key=f"del_{file['id']}", use_container_width=True):
                                with st.spinner("جاري الحذف..."):
                                    success, errors = delete_file(file['id'], file['file_path'])
                                    
                                    if success:
                                        st.success("✅ تم حذف الملف بنجاح من التخزين وقاعدة البيانات!")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ فشل الحذف: {' | '.join(errors)}")
                        
                        st.markdown("---")
    
    else:
        st.title("منصة التحليل الاستكشافي الآلي 🔐")
        tab1, tab2 = st.tabs(["تسجيل الدخول", "إنشاء حساب جديد"])
        
        with tab1:
            st.subheader("تسجيل الدخول")
            email = st.text_input("البريد الإلكتروني", key="login_email")
            password = st.text_input("كلمة المرور", type="password", key="login_password")
            if st.button("دخول"):
                if email and password:
                    login(email, password)
                else:
                    st.warning("الرجاء إدخال البريد الإلكتروني وكلمة المرور.")
                    
        with tab2:
            st.subheader("إنشاء حساب جديد")
            new_email = st.text_input("البريد الإلكتروني", key="signup_email")
            new_password = st.text_input("كلمة المرور", type="password", key="signup_password")
            confirm_password = st.text_input("تأكيد كلمة المرور", type="password", key="signup_confirm_password")
            if st.button("إنشاء الحساب"):
                if new_email and new_password and confirm_password:
                    if new_password == confirm_password:
                        signup(new_email, new_password)
                    else:
                        st.error("كلمتا المرور غير متطابقتين.")
                else:
                    st.warning("الرجاء ملء جميع الحقول.")

if __name__ == "__main__":
    main()