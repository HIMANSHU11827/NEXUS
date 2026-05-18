import requests
from bs4 import BeautifulSoup

def deep_scrape(url):
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    return soup.get_text()