from dotenv import load_dotenv
import os
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

print("Gemini 응답 테스트 중...")
response = model.generate_content("안녕하세요, 한 문장으로 짧게 답해주세요.")
print("응답:", response.text)
print("\n테스트 성공!")
