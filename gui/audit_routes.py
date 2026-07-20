import re

app_path = r'C:\Users\himan\Desktop\NEXUS AI\gui\src\App.tsx'
api_path  = r'C:\Users\himan\Desktop\NEXUS AI\gui\api.py'

with open(app_path,'r',encoding='utf-8') as f:
    app_src = f.read()

frontend_calls = sorted(set(re.findall(r'/api/[A-Za-z0-9/_.:-]+', app_src)))

with open(api_path,'r',encoding='utf-8') as f:
    api_src = f.read()

backend_routes = sorted(set(re.findall(r'@app\.(get|post|put|patch|delete)\("(/api/[A-Za-z0-9/_{}:.-]+)"', api_src)))

print('FRONTEND_CALLS:')
for url in frontend_calls:
    print(' ', url)
print('\nBACKEND_ROUTES:')
for route in backend_routes:
    print(' ', route)
