import streamlit as st
from supabase import create_client, Client
import socket

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

# --- إدارة حالة الجلسة (Session State) ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = None

# --- دوال المصادقة ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.logged_in = True
        st.session_state.user_email = email
        st.success("تم تسجيل الدخول بنجاح!")
        st.rerun()
    except socket.gaierror:
        st.error("تعذر الوصول إلى خادم Supabase. تحقق من رابط المشروع في secrets.toml وأن المشروع ما زال فعالًا.")
    except Exception as e:
        st.error(f"خطأ في تسجيل الدخول: {e}")

def signup(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        st.success("تم إنشاء الحساب بنجاح! يمكنك الآن تسجيل الدخول.")
    except socket.gaierror:
        st.error("تعذر الوصول إلى خادم Supabase. انسخ Project URL الحالي من Supabase Dashboard إلى secrets.toml.")
    except Exception as e:
        st.error(f"خطأ في إنشاء الحساب: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.logged_in = False
    st.session_state.user_email = None
    st.rerun()

# --- واجهة المستخدم الرئيسية ---
def main():
    if st.session_state.logged_in:
        st.title(f"مرحباً بك، {st.session_state.user_email} 👋")
        st.write("أنت الآن في الصفحة الرئيسية لمنصة التحليل الاستكشافي.")
        st.write("⚠️ المشروع قيد التطوير، سيتم إضافة صفحات التحليل قريباً!")
        
        if st.button("تسجيل الخروج"):
            logout()
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