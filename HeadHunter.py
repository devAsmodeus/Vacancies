import os
import asyncio
import random
import json

from tqdm import tqdm
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from colorama import Fore
from itertools import count
from bs4 import BeautifulSoup
from re import search

VERSION = '24.29.3.3'


async def main() -> None:
    while True:
        menu = await format_details()
        for country, region, city_id, city_name, role_id, role_name in set(menu):
            file_vacancies, new_vacancies = await get_file_vacancies(), set()
            print(f'На данный момент в хранилище {len(file_vacancies)} вакансий')
            try:
                for page in count(start=0, step=1):
                    print(f'Парсим вакансии: {country} / {region} / {city_name} / {role_name}. Страница {page + 1}')
                    page_vacancies = await parse_region_page(city_id, role_id, page)
                    new_vacancies, data = await send_vacancies(
                        vacancies=dict.get(page_vacancies, 'vacancies'),
                        file_vacancies=file_vacancies,
                        new_vacancies=new_vacancies
                    )
                    await asyncio.sleep(2)
                    if paging := dict.get(page_vacancies, 'paging', dict()):
                        if page == 19 or dict.get(paging, 'next', dict()).get('page') == page:
                            await upload_vacancies(file_vacancies | new_vacancies, data)
                            break
                    else:
                        await upload_vacancies(file_vacancies | new_vacancies, data)
                        break
            except Exception as exception:
                print(Fore.RED + repr(exception))
                await asyncio.sleep(120)


async def format_details() -> list[tuple]:
    async with ClientSession(headers=await get_headers(index=1), connector=TCPConnector(ssl=False)) as session:
        menu, urls = await parse_menu(session), list()
        menu = json.loads(menu.find(id='HH-Lux-InitialState').text)
        area, industries, roles = menu['areaTree'], menu['industriesTree'], menu['professionalRoleTree']
        for country in area:
            country_name = dict.get(country, 'text')
            if country_name == 'Россия':
                for region in dict.get(country, 'items', dict()):
                    region_id, region_name = dict.get(region, 'id'), dict.get(region, 'text')
                    for city in dict.get(region, 'items', dict()):
                        city_id, city_name = dict.get(city, 'id'), dict.get(city, 'text')
                        urls.extend(await format_roles(roles, country_name, region_name, city_id, city_name))
                    else:
                        urls.extend(await format_roles(roles, country_name, region_name, region_id, region_name))
        else:
            return urls


async def format_roles(roles, country, region, city_id, city_name):
    urls = list()
    for part_roles in dict.get(roles, 'items', dict()):
        for role in dict.get(part_roles, 'items', dict()):
            role_id, role_name = dict.get(role, 'id'), dict.get(role, 'text')
            urls.append((country, region, city_id, city_name, role_id, role_name))
    else:
        return urls


async def send_vacancies(vacancies: list[dict], file_vacancies: set, new_vacancies: set) -> tuple[set, list[str]]:
    data = list()
    async with ClientSession(headers=await get_headers(index=3), connector=TCPConnector(ssl=False)) as session:
        for vacancy in tqdm(vacancies, desc='Отправка вакансий по запросу'):
            vacancy_id = dict.get(vacancy, 'vacancyId')
            if vacancy_id not in file_vacancies and vacancy_id not in new_vacancies and '@isAdv' not in vacancy:
                if vacancy.get('@showContact') and (employer_id := vacancy.get('company', dict()).get('id')):
                    contacts = await parse_contacts(session, vacancy['vacancyId'], employer_id)
                    # first_url, first_data = await format_vacancy(vacancy, contacts, index=1)
                    second_url, second_data = await format_vacancy(vacancy, contacts, index=2)
                    data.append(second_data['data'])
                    await send_webhook(second_url, second_data)
                    new_vacancies.add(vacancy_id)
                    # for url, data in zip((first_url, second_url), (first_data, second_data)):
                    #     await send_webhook(url, data)
                    # else:
                    #     new_vacancies.add(vacancy_id)
                    await asyncio.sleep(random.random() * 5)
        else:
            return new_vacancies, data


async def format_vacancy(vacancy: dict, contacts: dict, index: int) -> tuple[str, dict]:
    if index == 1:
        url = 'https://cloud.roistat.com/integration/webhook?key=a58c86c38a259de63562d533d7c7edf4'
        return url, {
            'city': vacancy.get('area', dict()).get('name'),
            'company_name': vacancy.get('company', dict()).get('name'),
            'vacancy_url': vacancy.get('links', dict()).get('desktop'),
            "title": dict.get(vacancy, 'name'),
            "name": dict.get(contacts, 'fio'),
            "email": dict.get(contacts, 'email'),
            "phone": None,
            "comment": dict.get(vacancy, 'links', dict()).get('desktop'),
            "roistat_visit": dict.get(vacancy, 'creationSite'),
            "fields": {"site": "hh.ru", "source": "hh.ru", "promocode": None}
        }
    else:
        url = 'https://c6ce863bb1eb.vps.myjino.ru/contacts?apiKey=Wy7RXAzSRZpD4a3q'
        return url, {
            'vacancy_name': vacancy.get('name'),
            'city': vacancy.get('area', dict()).get('name'),
            'company_name': vacancy.get('company', dict()).get('name'),
            'vacancy_url': vacancy.get('links', dict()).get('desktop'),
            "source": "hh.ru", "name": dict.get(contacts, 'fio'),
            "email": dict.get(contacts, 'email'),
            "data": (
                f"{dict.get(vacancy, 'name')};"
                f"{vacancy.get('company', dict()).get('name')};"
                f"{dict.get(vacancy, 'links', dict()).get('desktop')};"
                f"{dict.get(contacts, 'fio')};"
                f"{dict.get(contacts, 'email')};"
                f"{dict.get(vacancy, 'area', dict()).get('name')}"
            )
        }


async def get_headers(index: int) -> dict:
    if index == 1:
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cache-Control': 'no-cache',
            'Cookie': 'hhuid=ogfiDIr3fZ9ztGaG9qYxQw--; _ym_uid=1720120998292002741; hhul=0c5a85594ce8b83931d9a664f0a63daa3131d8f2b9245a5a3d4fdd9865770d79; __ddg9_=46.53.254.169; __ddg1_=PBB8Ku4OGTb11nOSn9vU; _xsrf=b03ddeac4e6dc4f6323837eea50619ef; regions=1; region_clarified=NOT_SET; display=desktop; crypted_hhuid=24E9B4391513F61BC00B67F16B210B6407489A407DBA93F151E2EABEE0CF1BE1; GMT=3; tmr_lvid=1d4be8f47da74bb07c5394c3bf12e3be; tmr_lvidTS=1720120998391; _ym_d=1738009083; iap.uid=1cf6bdc1c46f452f8f04401f44134381; _ym_isad=2; _ym_visorc=w; domain_sid=1tIAOBVsSp5njm1l1ThII%3A1738009083999; uxs_uid=2e086ef0-3a3f-11ef-9fbb-99bb2b974093; crypted_id=E0154C375A09DD4F48A21CB2DE4073ABA5471C6F722104504734B32F0D03E9F8; hhtoken=OhVNryfiPApol9anLxkH3v6GAUe8; _hi=153726015; hhrole=applicant; __zzatgib-w-hh=MDA0dC0jViV+FmELHw4/aQsbSl1pCENQGC9LXy8sPCAdZHlgUnkPVn9WS0V3JVRTPA9jbklteFtBaiBoOVURCxIXRF5cVWl1FRpLSiVueCplJS0xViR8SylEXFAJJRkaeG4nTw0RVy8NPjteLW8PKhMjZHYhP04hC00+KlwVNk0mbjN3RhsJHlksfEspNVZ/elpMGn5yWQsPDRVDc3R3LEBtIV9PXlNEE34KJxkReyVXVQoOYEAzaWVpcC9gIBIlEU1HGEVkW0I2KBVLcU8cenZffSpCaCVfR2IgRllNfyoVe0M8YwxxFU11cjgzGxBhDyMOGFgJDA0yaFF7CT4VHThHKHIzd2UqQGgkYU1ZIEhHSWtlTlNCLGYbcRVNCA00PVpyIg9bOSVYCBI/CyYgFH9rI1gIDl89R3NvG382XRw5YxEOIRdGWF17TEA=IwdcIw==; tmr_detect=0%7C1738009135866; total_searches=2; device_magritte_breakpoint=m; device_breakpoint=m; __ddg8_=sUXgrdpMVLKrEDPo; __ddg10_=1738009318; gsscgib-w-hh=yLPkofxXtdRfeDlS5xiZjpeJowTXErRnh3kfW08CeZw2TK/hRVxhTd8BG8tUjIpsIoLwkqi5QxKvFTnUYbKBuTpusS2arlSj8cGAC5C5+Qv8MSq+KV76eUDcFFm4TXgyI07B8v+uS9ji85qEUke/RAWp5C9SzJdxAUZ4imLrsnu/doO+IaQ8mS3RW4xy1lRC6IGyCAEm0U5a3zpNKxYyWs/QwUBfP1Z8zuP/XoCCKLs5ssCXDgY42R8IX60YoBJI; cfidsgib-w-hh=I5+1S7ut5hrEhv5G5yD4CRrJU5r56odEMxGEuo3IJgNQxan89p1MSYVEwLhhrzKMvgXU80+/phH5yZMmrKNBS5qaMKfVygFW/EI/K4SVWGCGUxflfVmwcVPbDIe/TYOscywZhitVP5AhlB9Wq2sFk0VXHDm6FhyYC9vXMYo=; cfidsgib-w-hh=I5+1S7ut5hrEhv5G5yD4CRrJU5r56odEMxGEuo3IJgNQxan89p1MSYVEwLhhrzKMvgXU80+/phH5yZMmrKNBS5qaMKfVygFW/EI/K4SVWGCGUxflfVmwcVPbDIe/TYOscywZhitVP5AhlB9Wq2sFk0VXHDm6FhyYC9vXMYo=; gsscgib-w-hh=yLPkofxXtdRfeDlS5xiZjpeJowTXErRnh3kfW08CeZw2TK/hRVxhTd8BG8tUjIpsIoLwkqi5QxKvFTnUYbKBuTpusS2arlSj8cGAC5C5+Qv8MSq+KV76eUDcFFm4TXgyI07B8v+uS9ji85qEUke/RAWp5C9SzJdxAUZ4imLrsnu/doO+IaQ8mS3RW4xy1lRC6IGyCAEm0U5a3zpNKxYyWs/QwUBfP1Z8zuP/XoCCKLs5ssCXDgY42R8IX60YoBJI; fgsscgib-w-hh=l1UXdb2f1505e46dccf6007d676fd57cad165531',
            'Pragma': 'no-cache',
            'Priority': 'u=0, i',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        }
    elif index == 2:
        return {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ru-RU,ru;q=0.9',
            'Cookie': 'hhuid=ogfiDIr3fZ9ztGaG9qYxQw--; _ym_uid=1720120998292002741; hhul=0c5a85594ce8b83931d9a664f0a63daa3131d8f2b9245a5a3d4fdd9865770d79; __ddg9_=46.53.254.169; __ddg1_=PBB8Ku4OGTb11nOSn9vU; _xsrf=b03ddeac4e6dc4f6323837eea50619ef; regions=1; region_clarified=NOT_SET; display=desktop; crypted_hhuid=24E9B4391513F61BC00B67F16B210B6407489A407DBA93F151E2EABEE0CF1BE1; GMT=3; tmr_lvid=1d4be8f47da74bb07c5394c3bf12e3be; tmr_lvidTS=1720120998391; _ym_d=1738009083; iap.uid=1cf6bdc1c46f452f8f04401f44134381; _ym_isad=2; _ym_visorc=w; domain_sid=1tIAOBVsSp5njm1l1ThII%3A1738009083999; uxs_uid=2e086ef0-3a3f-11ef-9fbb-99bb2b974093; crypted_id=E0154C375A09DD4F48A21CB2DE4073ABA5471C6F722104504734B32F0D03E9F8; hhtoken=OhVNryfiPApol9anLxkH3v6GAUe8; _hi=153726015; hhrole=applicant; device_magritte_breakpoint=m; device_breakpoint=m; total_searches=1; __zzatgib-w-hh=MDA0dC0jViV+FmELHw4/aQsbSl1pCENQGC9LXy8sPCAdZHlgUnkPVn9WS0V3JVRTPA9jbklteFtBaiBoOVURCxIXRF5cVWl1FRpLSiVueCplJS0xViR8SylEXFAJJRkaeG4nTw0RVy8NPjteLW8PKhMjZHYhP04hC00+KlwVNk0mbjN3RhsJHlksfEspNVZ/elpMGn5yWQsPDRVDc3R3LEBtIV9PXlNEE34KJxkReyVXVQoOYEAzaWVpcC9gIBIlEU1HGEVkW0I2KBVLcU8cenZffSpCaCVfR2IgRllNfyoVe0M8YwxxFU11cjgzGxBhDyMOGFgJDA0yaFF7CT4VHThHKHIzd2UqQGgkYU1ZIEhHSWtlTlNCLGYbcRVNCA00PVpyIg9bOSVYCBI/CyYgFH9rI1gIDl89R3NvG382XRw5YxEOIRdGWF17TEA=IwdcIw==; gsscgib-w-hh=phypfq5vTRHqh7kcovbYsKSC1I5JJwlAWuYiVCtMyEwKrLlgwYUoe4HV0jXJa2w5ieriD1vcUbaUJdLFRDO9RJt7WaGJobtIVJEzEcZXBG/dkYcf5txGtV9u2c1wsGExu+ORaizvMjoqysIt0Bexyl5oHpCCkAe1TIhh8Kw3DeTLFPBx172z0WFqGTga2XYU0zvcEdGXE4igthKLV039/ikTL+NRQxTN1O4e7b3D/Y5gGjJ0kKW2nLQax5lfFB0u; cfidsgib-w-hh=mKzPX7Dz8Ps6MNPUoxALPjvcpE2jPhb8aicqkPP4KfK5tdLEat9KAQEQpwedgt5J2fMVVS9KSKnymOp5/qDbvxyO2YrhQWVrxGyBQeZA5jXNelbET05GWp0+fFnZK9PkMSaUhlpXH3r2gSolfpXApdbfNmWhWVN18Nf/chU=; cfidsgib-w-hh=mKzPX7Dz8Ps6MNPUoxALPjvcpE2jPhb8aicqkPP4KfK5tdLEat9KAQEQpwedgt5J2fMVVS9KSKnymOp5/qDbvxyO2YrhQWVrxGyBQeZA5jXNelbET05GWp0+fFnZK9PkMSaUhlpXH3r2gSolfpXApdbfNmWhWVN18Nf/chU=; gsscgib-w-hh=phypfq5vTRHqh7kcovbYsKSC1I5JJwlAWuYiVCtMyEwKrLlgwYUoe4HV0jXJa2w5ieriD1vcUbaUJdLFRDO9RJt7WaGJobtIVJEzEcZXBG/dkYcf5txGtV9u2c1wsGExu+ORaizvMjoqysIt0Bexyl5oHpCCkAe1TIhh8Kw3DeTLFPBx172z0WFqGTga2XYU0zvcEdGXE4igthKLV039/ikTL+NRQxTN1O4e7b3D/Y5gGjJ0kKW2nLQax5lfFB0u; tmr_detect=0%7C1738009135866; __ddg10_=1738009141; __ddg8_=sBhjrAYo9kwZJ2KL; fgsscgib-w-hh=ek8Pf947b75878233f824329df096619b158b0a5',
            'Priority': 'u=1, i',
            'Referer': 'https://hh.ru/search/vacancy?area=1&ored_clusters=true&order_by=publication_time',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'X-Gib-Fgsscgib-W-Hh': 'Rjy61c74afefb375c1d175d837fc688f98f0b11a',
            'X-Gib-Gsscgib-W-Hh': 'MNyFQ5W1z0UErlzo1/SgaIsjXVYMpR8OzUeoUJsPtn9yHaxeib4JwZLlUvwzK0/cvhuT3QegDEwfsCyaSlR9rn1XNdoIBbB2FssEnYrqqIZlab41sGOOmCv85PgTIss0t7qLiykvMyIc7ypcKWfzmvhahOIWieGqtF+AOiDr9A7U1LCNcWRvwG40ljfcISeoYslRAfKE60SJFJ268JqLVj+2DsO4MGWWXQ03TtrfdAdfFYWZDuW+i6MdDln/WZOL8w==',
            'X-Hhtmfrom': 'vacancy_search_filter',
            'X-Hhtmfromlabel': 'X-Hhtmsource',
            'X-Requested-With': 'XMLHttpRequest',
            'X-Static-Version': VERSION,
            'X-Xsrftoken': '696f6f77c6fd5206279bf310a9ed9a47'
        }
    else:
        return {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cookie': 'hhuid=ogfiDIr3fZ9ztGaG9qYxQw--; _ym_uid=1720120998292002741; hhul=0c5a85594ce8b83931d9a664f0a63daa3131d8f2b9245a5a3d4fdd9865770d79; __ddg1_=PBB8Ku4OGTb11nOSn9vU; _xsrf=b03ddeac4e6dc4f6323837eea50619ef; region_clarified=NOT_SET; display=desktop; crypted_hhuid=24E9B4391513F61BC00B67F16B210B6407489A407DBA93F151E2EABEE0CF1BE1; GMT=3; tmr_lvid=1d4be8f47da74bb07c5394c3bf12e3be; tmr_lvidTS=1720120998391; _ym_d=1738009083; iap.uid=1cf6bdc1c46f452f8f04401f44134381; uxs_uid=2e086ef0-3a3f-11ef-9fbb-99bb2b974093; total_searches=3; regions=1; __ddg9_=46.53.254.169; _ym_isad=2; _ym_visorc=w; domain_sid=1tIAOBVsSp5njm1l1ThII%3A1738320950724; remember=0; lrp=""; lrr=""; crypted_id=E0154C375A09DD4F48A21CB2DE4073ABA5471C6F722104504734B32F0D03E9F8; hhtoken=Mszg_Vy1pTdi1!hgeNUFQQ!h0lwB; _hi=153726015; hhrole=applicant; device_breakpoint=l; tmr_detect=0%7C1738320992498; device_magritte_breakpoint=xxl; __zzatgib-w-hh=MDA0dC0jViV+FmELHw4/aQsbSl1pCENQGC9LXzFabmVPGElfUEpVVXosShh3J1lUCg8WQkgmeV8+ak8aOVURCxIXRF5cVWl1FRpLSiVueCplJS0xViR8SylEXFAJKBsSd2wrTw4MVy8NPjteLW8PKhMjZHYhP04hC00+KlwVNk0mbjN3RhsJHlksfEspNVZ/elpMGn5yWQsPDRVDc3R3LEBtIV9PXlNEE34KJxkReyVXVQoOYEAzaWVpcC9gIBIlEU1HGEVkW0I2KBVLcU8cenZffSpCaCViSVofRF1Nfy4Ve0M8YwxxFU11cjgzGxBhDyMOGFgJDA0yaFF7CT4VHThHKHIzd2UqQGgkYU1ZIEhHSWtlTlNCLGYbcRVNCA00PVpyIg9bOSVYCBI/CyYgFH9uJVB/DGM9SG1vG382XRw5YxEOIRdGWF17TEA=WmY/8g==; __ddg8_=LfS8okKWQCU7rtuZ; __ddg10_=1738321019; gsscgib-w-hh=0d25eVRBo+7+tp482DKi/jFFCW2VDHC+vNcQONDrfQvNwCGDvYdQiH23JOwLEtfCs2YmZciLIUf5rs55TajCc8BTbNj8rlwqprqct/n6DcHXG46KGlDmrTuAI/gYCAwHMxeWEyl4Nc37lI3LO2H2e+yc10jPy/TR6XNvlrCeN+bVQHKZC47omccURb3AXGybpWAy8OlUizH+f5WnJL3TKv/jFlrBJFKOXh5F6FH1093fJvPmi8DM15hpcQHQV5z1iV6Wf0+cnb9SGrV0; cfidsgib-w-hh=ZU2ycCedw3d/SSvxSGe2icYwEjsw2JAN2L6YzDnnUrn/DvHD6+71GXxBtzTjJGdb8I2+EPbFnRub0RRmgny6UHiHk7e3JNGcP+AvABkPVEeVa2220pb2bBQGY4msN3xNc2wiP1llPKwU2mVGLfooYeAGuS+cVzwUa03uOA8=; cfidsgib-w-hh=ZU2ycCedw3d/SSvxSGe2icYwEjsw2JAN2L6YzDnnUrn/DvHD6+71GXxBtzTjJGdb8I2+EPbFnRub0RRmgny6UHiHk7e3JNGcP+AvABkPVEeVa2220pb2bBQGY4msN3xNc2wiP1llPKwU2mVGLfooYeAGuS+cVzwUa03uOA8=; gsscgib-w-hh=0d25eVRBo+7+tp482DKi/jFFCW2VDHC+vNcQONDrfQvNwCGDvYdQiH23JOwLEtfCs2YmZciLIUf5rs55TajCc8BTbNj8rlwqprqct/n6DcHXG46KGlDmrTuAI/gYCAwHMxeWEyl4Nc37lI3LO2H2e+yc10jPy/TR6XNvlrCeN+bVQHKZC47omccURb3AXGybpWAy8OlUizH+f5WnJL3TKv/jFlrBJFKOXh5F6FH1093fJvPmi8DM15hpcQHQV5z1iV6Wf0+cnb9SGrV0; fgsscgib-w-hh=jlLX539f277e0f28993e245fb0249be9589d8879',
            'Priority': 'u=1, i',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'X-Gib-Fgsscgib-W-Hh': 'jlLX539f277e0f28993e245fb0249be9589d8879',
            'X-Gib-Gsscgib-W-Hh': '0d25eVRBo+7+tp482DKi/jFFCW2VDHC+vNcQONDrfQvNwCGDvYdQiH23JOwLEtfCs2YmZciLIUf5rs55TajCc8BTbNj8rlwqprqct/n6DcHXG46KGlDmrTuAI/gYCAwHMxeWEyl4Nc37lI3LO2H2e+yc10jPy/TR6XNvlrCeN+bVQHKZC47omccURb3AXGybpWAy8OlUizH+f5WnJL3TKv/jFlrBJFKOXh5F6FH1093fJvPmi8DM15hpcQHQV5z1iV6Wf0+cnb9SGrV0',
            'X-Hhtmfrom': 'vacancy_search_filter',
            'X-Hhtmsource': 'vacancy_search_list',
            'X-Requested-With': 'XMLHttpRequest',
            'X-Xsrftoken': 'b03ddeac4e6dc4f6323837eea50619ef'
        }


async def get_file_vacancies() -> set:
    filename, vacancies = r'./VacanciesHHRU.json', set()
    if os.path.exists(filename):
        with open(file=filename, mode='r+') as file:
            return set(json.load(file)['vacanciesId'])
    else:
        with open(file=filename, mode='w+', encoding='utf-8') as file:
            json.dump(dict(vacanciesId=list(vacancies)), file, ensure_ascii=False)
            return vacancies


async def upload_vacancies(vacancies: set[int], data: list[str]) -> None:
    with open(file=r'./VacanciesHHRU.json', mode='w+', encoding='utf-8') as file:
        json.dump(dict(vacanciesId=list(vacancies)), file, ensure_ascii=False)
    if data:
        if os.path.exists(r'./VacanciesHHRU.txt'):
            with open(file=r'./VacanciesHHRU.txt', mode='a+', encoding='utf-8') as file:
                file.writelines(row + '\n' for row in data)
        else:
            with open(file=r'./VacanciesHHRU.txt', mode='w+', encoding='utf-8') as file:
                file.writelines(row + '\n' for row in data)


async def send_webhook(url: str, data: dict) -> bool:
    async with ClientSession(connector=TCPConnector(ssl=False)) as session:
        async with session.post(url=url, json=data) as response:
            if response.status == 200:
                return True
            else:
                print(f"Ошибка при отправке вебхука. Статус: {response.status} {await response.text()}")
                return False


async def parse_status() -> str:
    async with ClientSession(headers=await get_headers(index=1), connector=TCPConnector(ssl=False)) as session:
        while True:
            try:
                async with session.get(
                        url=f'https://hh.ru/search/vacancy?L_save_area=true&text=&excluded_text=&area=7232&area=1217&'
                            f'salary=&currency_code=RUR&experience=doesNotMatter&order_by=relevance&search_period=0&'
                            f'items_on_page=50&hhtmFrom=vacancy_search_filter',
                        timeout=ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        print(response.status)
                        await asyncio.sleep(5)
            except Exception as exception:
                print(repr(exception))
                await asyncio.sleep(30)


async def parse_contacts(session: ClientSession, vacancy_id: int, employer_id: int) -> dict:
    while True:
        try:
            async with session.get(
                    url=f'https://hh.ru/vacancy/{vacancy_id}/contacts?employerId={employer_id}',
                    timeout=ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return dict()
        except Exception as exception:
            print(repr(exception))
            await asyncio.sleep(30)


async def parse_region_page(area_id: str, role_id: str, page: int) -> dict:
    while True:
        async with ClientSession(headers=await get_headers(index=2), connector=TCPConnector(ssl=False)) as session:
            try:
                async with session.get(
                        url='https://hh.ru/search/vacancy?'
                        'L_save_area=true&'
                        'text=&'
                        'excluded_text=&'
                        f'professional_role={role_id}&'
                        f'area={area_id}&'
                        'salary=&'
                        'currency_code=RUR&'
                        'experience=doesNotMatter&'
                        'order_by=publication_time&'
                        'search_period=0&'
                        'items_on_page=100&'
                        f'page={page}&'
                        'disableBrowserCache=true',
                        timeout=ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        return (await response.json())['vacancySearchResult']
                    elif response.status == 406:
                        await asyncio.sleep(random.random() * 2)
                        text = await parse_status()
                        global VERSION
                        VERSION = search(r'build:\s*"([^"]*)"', text).group(1)
                    else:
                        print(response.status)
                        await asyncio.sleep(30)
            except Exception as exception:
                print(repr(exception))
                await asyncio.sleep(30)


async def parse_menu(session: ClientSession) -> BeautifulSoup:
    while True:
        try:
            async with session.get(
                    url='https://hh.ru/search/vacancy/advanced?hhtmFrom=main',
                    timeout=ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    return BeautifulSoup(await response.text(), 'html.parser')
                else:
                    print(response.status)
                    await asyncio.sleep(30)
        except Exception as exception:
            print(repr(exception))
            await asyncio.sleep(30)


if __name__ == '__main__':
    asyncio.run(main())
