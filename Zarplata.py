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

VERSION = '24.35.6'


async def main() -> None:
    while True:
        menu, sort_type = await format_details()
        for region, city_id, city_name, role_id, role_name in set(menu):
            file_vacancies, new_vacancies = await get_file_vacancies(), set()
            print(f'На данный момент в хранилище {len(file_vacancies)} вакансий')
            try:
                for page in count(start=0, step=1):
                    print(f'Парсим вакансии: {region} / {city_name} / {role_name}. Страница {page + 1}')
                    page_vacancies = await parse_region_page(city_id, role_id, page, sort_type)
                    new_vacancies = await send_vacancies(
                        vacancies=dict.get(page_vacancies, 'vacancies'),
                        file_vacancies=file_vacancies,
                        new_vacancies=new_vacancies
                    )
                    await asyncio.sleep(2)
                    if paging := dict.get(page_vacancies, 'paging', dict()):
                        if page == 19 or dict.get(paging, 'next', dict()).get('page') == page:
                            await upload_vacancies(file_vacancies | new_vacancies)
                            break
                    else:
                        await upload_vacancies(file_vacancies | new_vacancies)
                        break
            except Exception as exception:
                print(Fore.RED + repr(exception))
                await asyncio.sleep(120)


async def format_details() -> tuple[list[tuple], str]:
    headers, connector = get_headers(index=1), TCPConnector(ssl=False)
    result, (sort_type, settings_areas, settings_roles) = list(), format_setting()
    async with ClientSession(headers=headers, connector=connector) as session:
        menu: BeautifulSoup = await parse_menu(session)
        menu: dict = json.loads(menu.find(id='HH-Lux-InitialState').text)
        areas, roles = menu.get('areaTree', list()), menu.get('professionalRoleTree', dict())
        for area in areas:
            area_id, area_name = area.get('id'), area.get('text')
            for city in area.get('items', dict()):
                city_id, city_name = city.get('id'), city.get('text')
                parameters = area_name, city_id, city_name
                result.extend(format_roles(roles, settings_areas, settings_roles, parameters))
            else:
                parameters = area_name, area_id, area_name
                result.extend(format_roles(roles, settings_areas, settings_roles, parameters))
        else:
            return result, sort_type


def format_roles(roles: dict, settings_areas: list[str], settings_roles: list[str], *args) -> list[tuple]:
    result, (region, area_id, area_name) = list(), *args
    for part_roles in roles.get('items', dict()):
        for role in part_roles.get('items', dict()):
            role_id, role_name = role.get('id'), role.get('text')
            if role_id in settings_roles and area_id in settings_areas:
                result.append((region, area_id, area_name, role_id, role_name))
    else:
        return result


async def send_vacancies(vacancies: list[dict], file_vacancies: set, new_vacancies: set) -> set:
    async with ClientSession(headers=get_headers(index=3), connector=TCPConnector(ssl=False)) as session:
        for vacancy in tqdm(vacancies, desc='Отправка вакансий по запросу'):
            vacancy_id = dict.get(vacancy, 'vacancyId')
            if vacancy_id not in file_vacancies and vacancy_id not in new_vacancies and '@isAdv' not in vacancy:
                if dict.get(vacancy, '@showContact') and (employer_id := dict.get(vacancy, 'company', dict()).get('id')):
                    if contacts := await parse_contacts(session, vacancy['vacancyId'], employer_id):
                        first_url, first_data = await format_vacancy(vacancy, contacts, index=1)
                        second_url, second_data = await format_vacancy(vacancy, contacts, index=2)
                        for url, data in zip((first_url, second_url), (first_data, second_data)):
                            await send_webhook(url, data)
                        else:
                            new_vacancies.add(vacancy_id)
                    else:
                        await asyncio.sleep(random.random() * 5)
        else:
            return new_vacancies


async def format_vacancy(vacancy: dict, contacts: dict, index: int) -> tuple[str, dict]:
    phone = None
    if phones := dict.get(contacts, 'phones', dict()).get('phones'):
        for phone_data in phones:
            phone = f'+{phone_data["country"]}{phone_data["city"]}{phone_data["number"]}'
            break
    if index == 1:
        url = 'https://cloud.roistat.com/integration/webhook?key=a58c86c38a259de63562d533d7c7edf4'
        return url, {
            'city': vacancy.get('area', dict()).get('name'),
            'company_name': vacancy.get('company', dict()).get('name'),
            'vacancy_url': vacancy.get('links', dict()).get('desktop'),
            'title': dict.get(vacancy, 'name'),
            'name': dict.get(contacts, 'fio'),
            "email": dict.get(contacts, 'email'),
            "phone": phone,
            "comment": dict.get(vacancy, 'links', dict()).get('desktop'),
            "roistat_visit": dict.get(vacancy, 'creationSite'),
            "fields": {"site": "zarplata.ru", "source": "zarplata.ru", "promocode": None}
        }
    else:
        url = 'https://c6ce863bb1eb.vps.myjino.ru/contacts?apiKey=Wy7RXAzSRZpD4a3q'
        return url, {
            'vacancy_name': vacancy.get('name'),
            'city': vacancy.get('area', dict()).get('name'),
            'company_name': vacancy.get('company', dict()).get('name'),
            'vacancy_url': vacancy.get('links', dict()).get('desktop'),
            "source": "zarplata.ru", "name": dict.get(contacts, 'fio'),
            "email": dict.get(contacts, 'email'), "phone": phone,
            "data": (
                f"{dict.get(vacancy, 'name')};"
                f"{vacancy.get('company', dict()).get('name')};"
                f"{dict.get(vacancy, 'links', dict()).get('desktop')};"
                f"{dict.get(contacts, 'fio')};"
                f"{dict.get(contacts, 'email')};"
                f"{phone};"
                f"{dict.get(vacancy, 'area', dict()).get('name')}"
            )
        }


def get_headers(index: int) -> dict:
    if index == 1:
        return {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'cache-control': 'max-age=0',
            'cookie': 'hhuid=ntaK0QMGHo3LHWbPaIE0QQ--; _ym_uid=1724868735174098285; _ym_d=1724868735; hhul=0c5a85594ce8b83931d9a664f0a63daa3131d8f2b9245a5a3d4fdd9865770d79; __ddg9_=46.53.254.169; __ddg1_=5dtOtxSK8TY1uEoHj0xH; _xsrf=0e9742f925f82faff2388790c9b25efb; region_fixed=true; display=desktop; cookies_fixed=true; GMT=3; tmr_lvid=b803fd8beea321b83e662e8bd394e6e1; tmr_lvidTS=1724868735057; device_breakpoint=l; _ym_isad=2; _ym_visorc=w; domain_sid=JPS4myBKHvvDhbN7sPWKy%3A1737583788489; iap.uid=c07ba285745b4cc8869192794fe70583; region_clarified=NOT_SET; hhtoken=ZU8mqj_!9INSq7J8wuXdfcZYVlqu; _hi=165052394; hhrole=applicant; regions=""; total_searches=4; device_magritte_breakpoint=l; __zzatgib-w-hh=MDA0dC0jViV+FmELHw4/aQsbSl1pCENQGC9LXy8sPCAdZHlgUnkPVn9WS0V3JVRTPA9jbklteFtBaiBoOVURCxIXRF5cVWl1FRpLSiVueCplJS0xViR8SylEXFAIKiEVeGsnUwkQVy8NPjteLW8PKhMjZHYhP04hC00+KlwVNk0mbjN3RhsJHlksfEspNVZ/elpMGn5yWQsPDRVDc3R3LEBtIV9PXlNEE34KJxkReyVXVQoOYEAzaWVpcC9gIBIlEU1HGEVkW0I2KBVLcU8cenZffSpCaCRkT10gQ1lReykVe0M8YwxxFU11cjgzGxBhDyMOGFgJDA0yaFF7CT4VHThHKHIzd2UqQWodZElcKEdHSWtlTlNCLGYbcRVNCA00PVpyIg9bOSVYCBI/CyYgFH5wK1MIC19BQ3FvG382XRw5YxEOIRdGWF17TEA=v4QRng==; tmr_detect=0%7C1737584106459; gsscgib-w-hh=XsmUBMxC3wL0ugB0gnmnJVNdsDC6oYrlS0w8Q+FMxkjJ5ymQ7IJJ90Nlegjl3iI5BZG38gABXnZGspbpa5TKE1VJdosCeY/aSmRE4mHRtB33zGcQnqzZ/6jtbNUx6gGSmmq7Ahz+eWAvFwyMP5q6fhVJxCj9p+kM4exnwiWuFBic9muPN3+GKsieuEl5P2l1IrfvEZxffNUfippibjI+c0YA3c/lkFJPn6ArBKq0GrIiEFraEtmJgy2H4CeiXL1wgyhfxA==; cfidsgib-w-hh=d6+TJhGlc+mfknq6Fr1u/nYvWqGCRkpxg/b2HMOTnPMMenlD2bAPLxtwb4D+YTgTh3tyZJslCERGDmdHmz5CyQIS+p+9tO+PtQOkVWHOTFSCnxQ4CwyQsc/AUIdNMAuEgMQHtAbWOlGL1hcrG2uCvrB+YkM5fHbwuubbNF0=; cfidsgib-w-hh=d6+TJhGlc+mfknq6Fr1u/nYvWqGCRkpxg/b2HMOTnPMMenlD2bAPLxtwb4D+YTgTh3tyZJslCERGDmdHmz5CyQIS+p+9tO+PtQOkVWHOTFSCnxQ4CwyQsc/AUIdNMAuEgMQHtAbWOlGL1hcrG2uCvrB+YkM5fHbwuubbNF0=; gsscgib-w-hh=XsmUBMxC3wL0ugB0gnmnJVNdsDC6oYrlS0w8Q+FMxkjJ5ymQ7IJJ90Nlegjl3iI5BZG38gABXnZGspbpa5TKE1VJdosCeY/aSmRE4mHRtB33zGcQnqzZ/6jtbNUx6gGSmmq7Ahz+eWAvFwyMP5q6fhVJxCj9p+kM4exnwiWuFBic9muPN3+GKsieuEl5P2l1IrfvEZxffNUfippibjI+c0YA3c/lkFJPn6ArBKq0GrIiEFraEtmJgy2H4CeiXL1wgyhfxA==; __ddg8_=CiYOkheyWEha6Qkg; __ddg10_=1737584730; fgsscgib-w-hh=omAL45eca1bc94a32fb906250db5cb029d94858a',
            'priority': 'u=0, i',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
        }
    elif index == 2:
        return {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cookie': 'hhuid=ntaK0QMGHo3LHWbPaIE0QQ--; _ym_uid=1724868735174098285; _ym_d=1724868735; hhul=0c5a85594ce8b83931d9a664f0a63daa3131d8f2b9245a5a3d4fdd9865770d79; __ddg9_=46.53.254.169; __ddg1_=5dtOtxSK8TY1uEoHj0xH; _xsrf=0e9742f925f82faff2388790c9b25efb; region_fixed=true; display=desktop; cookies_fixed=true; GMT=3; tmr_lvid=b803fd8beea321b83e662e8bd394e6e1; tmr_lvidTS=1724868735057; device_breakpoint=l; _ym_isad=2; _ym_visorc=w; domain_sid=JPS4myBKHvvDhbN7sPWKy%3A1737583788489; iap.uid=c07ba285745b4cc8869192794fe70583; region_clarified=NOT_SET; hhtoken=ZU8mqj_!9INSq7J8wuXdfcZYVlqu; _hi=165052394; hhrole=applicant; regions=""; total_searches=7; device_magritte_breakpoint=xxl; __zzatgib-w-hh=MDA0dC0jViV+FmELHw4/aQsbSl1pCENQGC9LXy8sPCAdZHlgUnkPVn9WS0V3JVRTPA9jbklteFtBaiBoOVURCxIXRF5cVWl1FRpLSiVueCplJS0xViR8SylEXFAIKiEVf2wkVQ0TVy8NPjteLW8PKhMjZHYhP04hC00+KlwVNk0mbjN3RhsJHlksfEspNVZ/elpMGn5yWQsPDRVDc3R3LEBtIV9PXlNEE34KJxkReyVXVQoOYEAzaWVpcC9gIBIlEU1HGEVkW0I2KBVLcU8cenZffSpCaCRkT10nRFZTfy0Ve0M8YwxxFU11cjgzGxBhDyMOGFgJDA0yaFF7CT4VHThHKHIzd2UqQWodZElcKEdHSWtlTlNCLGYbcRVNCA00PVpyIg9bOSVYCBI/CyYgFH5wK1MPDFxDR3VvG382XRw5YxEOIRdGWF17TEA=lIpfag==; gsscgib-w-hh=vJXY0T8dsXPhUuNs+dsle3UiTC/id/n6aZBaVn2es3C77vnkACDLkHodxKwOC42wiHTnvvoF1JM9ttaHPEBsIFcDgBaFl4XHRrip5gToisLAdNrcxKbjT/31zQppvm0NTxs0GAak7M39TnhYYN0g2uQTtv3mBHkgmn7tQOq3gEOAWdgoiOCd1h6fgBEwN5EPpKy8rhr8nJXbde2Yyb4U2p4E7Tqh3fXUzSCEZQ8IH78pHeh1lVWIqh9+o8dTVIdk8BRzAw==; cfidsgib-w-hh=HdE8QLL90E8IZVF+gxRkwEojnmw9Q0R/jTL+7lavhkDtMLHqKWgzazaJqm63LBumwqB5crM9VoOoC73y82S4FvpJN0ZCeCWC+NB7kY906qH6yFaj4iK1ir51nQz+SL/6nI9qbDbqVDFcddgLygEzLLNfwBUBJgpou9cKUyw=; cfidsgib-w-hh=HdE8QLL90E8IZVF+gxRkwEojnmw9Q0R/jTL+7lavhkDtMLHqKWgzazaJqm63LBumwqB5crM9VoOoC73y82S4FvpJN0ZCeCWC+NB7kY906qH6yFaj4iK1ir51nQz+SL/6nI9qbDbqVDFcddgLygEzLLNfwBUBJgpou9cKUyw=; gsscgib-w-hh=vJXY0T8dsXPhUuNs+dsle3UiTC/id/n6aZBaVn2es3C77vnkACDLkHodxKwOC42wiHTnvvoF1JM9ttaHPEBsIFcDgBaFl4XHRrip5gToisLAdNrcxKbjT/31zQppvm0NTxs0GAak7M39TnhYYN0g2uQTtv3mBHkgmn7tQOq3gEOAWdgoiOCd1h6fgBEwN5EPpKy8rhr8nJXbde2Yyb4U2p4E7Tqh3fXUzSCEZQ8IH78pHeh1lVWIqh9+o8dTVIdk8BRzAw==; tmr_detect=0%7C1737584813763; __ddg10_=1737584819; __ddg8_=2oq6wltAynqdKAYf; fgsscgib-w-hh=IBg2b7b2dabd5d059d6eb682016a8d0e36eacad2',
            'Priority': 'u=1, i',
            'Referer': 'https://zarplata.ru/search/vacancy?area=1&ored_clusters=true&order_by=publication_time',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'X-Gib-Fgsscgib-W-Hh': 'oJgF28b56942c2e49214a02c85526f41ad8e4e03',
            'X-Gib-Gsscgib-W-Hh': 'DJQJqS+Sg7vmxz+/iAfWrGKBiP/htwBWXhS+rLIhRx1cfbtrTUtjuBLX5GvrWe4IYAVdNEJlhs3oLUwhVIuJoodF0vfEdlniVCsV77IWx2n8Wc/0SBnrsmoDgBeR09OHyfwAGnSA3jQ0nqkLfMIiso1JbnyD2CUtdzKmAfKvgfxYiESLkKbwtHivqbi8/4FGxOy21BX3LwUufzMW5sA/smnTUO26B6YCqAod969zjpaHEdEqC4N1wZUDrCC57g==',
            'x-hhtmfrom': 'vacancy_search_filter',
            'x-hhtmfromlabel': '',
            'x-hhtmsource': '',
            'x-requested-with': 'XMLHttpRequest',
            'x-static-version': VERSION,
            'x-xsrftoken': '0e9742f925f82faff2388790c9b25efb'
        }
    else:
        return {
            'accept': 'application/json',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'cookie': 'hhuid=ntaK0QMGHo3LHWbPaIE0QQ--; _ym_uid=1724868735174098285; _ym_d=1724868735; hhul=0c5a85594ce8b83931d9a664f0a63daa3131d8f2b9245a5a3d4fdd9865770d79; __ddg9_=46.53.254.169; __ddg1_=5dtOtxSK8TY1uEoHj0xH; _xsrf=0e9742f925f82faff2388790c9b25efb; region_fixed=true; display=desktop; cookies_fixed=true; GMT=3; tmr_lvid=b803fd8beea321b83e662e8bd394e6e1; tmr_lvidTS=1724868735057; device_breakpoint=l; _ym_isad=2; _ym_visorc=w; domain_sid=JPS4myBKHvvDhbN7sPWKy%3A1737583788489; iap.uid=c07ba285745b4cc8869192794fe70583; region_clarified=NOT_SET; hhtoken=ZU8mqj_!9INSq7J8wuXdfcZYVlqu; _hi=165052394; hhrole=applicant; regions=""; device_magritte_breakpoint=xxl; __zzatgib-w-hh=MDA0dC0jViV+FmELHw4/aQsbSl1pCENQGC9LXy8sPCAdZHlgUnkPVn9WS0V3JVRTPA9jbklteFtBaiBoOVURCxIXRF5cVWl1FRpLSiVueCplJS0xViR8SylEXFAIKiEVf2wkVQ0TVy8NPjteLW8PKhMjZHYhP04hC00+KlwVNk0mbjN3RhsJHlksfEspNVZ/elpMGn5yWQsPDRVDc3R3LEBtIV9PXlNEE34KJxkReyVXVQoOYEAzaWVpcC9gIBIlEU1HGEVkW0I2KBVLcU8cenZffSpCaCRkT10nRFZTfy0Ve0M8YwxxFU11cjgzGxBhDyMOGFgJDA0yaFF7CT4VHThHKHIzd2UqQWodZElcKEdHSWtlTlNCLGYbcRVNCA00PVpyIg9bOSVYCBI/CyYgFH5wK1MPDFxDR3VvG382XRw5YxEOIRdGWF17TEA=lIpfag==; tmr_detect=0%7C1737584813763; total_searches=8; __ddg8_=hAzZoCpUxK2NdWW4; __ddg10_=1737584840; gsscgib-w-hh=2pCJjkfUGke0G8u2S4wt2YVdJRPcO7PlqyEM1XtTDuJxaqsKA3DFpC3MR2W+QnD3+nZQ5Szlz/1dYsSD3PTI7PgoFQZHjUsW2KiDa+hwZ3m87/ACaiBgacanz+QO8P1d4ILFyPQ9+cTOOjKY0hmEnmRFllahNjZZ4yWtBvc8C9gGjfpn7Wg35ImuxyaKrj7rFFG19UAQVAOuj3Ez/OEFTpzXsPXKFlO2bUE4dnqx15BxOHt2oXmdKUYhZr0sDuiB+AxEdA==; cfidsgib-w-hh=HezEujWbZPJSkHcsTlUUwChOYC1DDmpfOpA+U7wHILR+Kazj7VmZHddb330DFm1E6TUbXopuz2CC2xZmmlRbtJpnrs9RoCTsKh4RIzqgPbG6Z7CYlSZgTTVdVOSzjcI4wG2Clg28VbJMXZbMZwUZGcXLHIZ8uXkDSZ9LvZw=; cfidsgib-w-hh=HezEujWbZPJSkHcsTlUUwChOYC1DDmpfOpA+U7wHILR+Kazj7VmZHddb330DFm1E6TUbXopuz2CC2xZmmlRbtJpnrs9RoCTsKh4RIzqgPbG6Z7CYlSZgTTVdVOSzjcI4wG2Clg28VbJMXZbMZwUZGcXLHIZ8uXkDSZ9LvZw=; gsscgib-w-hh=2pCJjkfUGke0G8u2S4wt2YVdJRPcO7PlqyEM1XtTDuJxaqsKA3DFpC3MR2W+QnD3+nZQ5Szlz/1dYsSD3PTI7PgoFQZHjUsW2KiDa+hwZ3m87/ACaiBgacanz+QO8P1d4ILFyPQ9+cTOOjKY0hmEnmRFllahNjZZ4yWtBvc8C9gGjfpn7Wg35ImuxyaKrj7rFFG19UAQVAOuj3Ez/OEFTpzXsPXKFlO2bUE4dnqx15BxOHt2oXmdKUYhZr0sDuiB+AxEdA==; fgsscgib-w-hh=GpC670cc8ca4c0c0bcf222838cdfc87ec4bbae99',
            'priority': 'u=1, i',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'x-gib-fgsscgib-w-hh': 'GpC670cc8ca4c0c0bcf222838cdfc87ec4bbae99',
            'x-gib-gsscgib-w-hh': '2pCJjkfUGke0G8u2S4wt2YVdJRPcO7PlqyEM1XtTDuJxaqsKA3DFpC3MR2W+QnD3+nZQ5Szlz/1dYsSD3PTI7PgoFQZHjUsW2KiDa+hwZ3m87/ACaiBgacanz+QO8P1d4ILFyPQ9+cTOOjKY0hmEnmRFllahNjZZ4yWtBvc8C9gGjfpn7Wg35ImuxyaKrj7rFFG19UAQVAOuj3Ez/OEFTpzXsPXKFlO2bUE4dnqx15BxOHt2oXmdKUYhZr0sDuiB+AxEdA==',
            'x-hhtmfrom': 'vacancy_search_filter',
            'x-hhtmsource': 'vacancy_search_list',
            'x-requested-with': 'XMLHttpRequest',
            'x-xsrftoken': '0e9742f925f82faff2388790c9b25efb'
        }


def format_setting() -> tuple[str, list[str], list[str]]:
    settings = get_settings()
    for parser in settings.get('parsers', list()):
        if parser.get('name') == 'zarplata.ru':
            areas = parser.get('structure', dict()).get('areas', list())
            roles = parser.get('structure', dict()).get('roles', list())
            for sort_type, value in parser.get('structure', dict()).get('sorted', dict()).items():
                if value:
                    return sort_type, areas, roles
            else:
                return 'relevance', areas, roles
    else:
        raise ValueError('Не найдены настройки для текущего парсера')


def get_settings() -> dict:
    filename = r'./SearchSettings.json'
    if os.path.exists(filename):
        with open(file=filename, mode='r') as file:
            return json.load(file)
    else:
        raise FileNotFoundError('Файл с настройками не найден')


async def get_file_vacancies() -> set:
    filename, vacancies = r'./VacanciesZarplataRU.json', set()
    if os.path.exists(filename):
        with open(file=filename, mode='r+') as file:
            return set(json.load(file)['vacanciesId'])
    else:
        with open(file=filename, mode='w+', encoding='utf-8') as file:
            json.dump(dict(vacanciesId=list(vacancies)), file, ensure_ascii=False)
            return vacancies


async def upload_vacancies(vacancies: set) -> None:
    with open(file=r'./VacanciesZarplataRU.json', mode='w+', encoding='utf-8') as file:
        json.dump(dict(vacanciesId=list(vacancies)), file, ensure_ascii=False)


async def send_webhook(url: str, data: dict) -> bool:
    async with ClientSession(connector=TCPConnector(ssl=False)) as session:
        async with session.post(url=url, json=data) as response:
            if response.status == 200:
                return True
            else:
                print(f"Ошибка при отправке вебхука. Статус: {response.status}")
                return False


async def parse_status() -> str:
    async with ClientSession(headers=get_headers(index=1), connector=TCPConnector(ssl=False)) as session:
        while True:
            try:
                async with session.get(
                        url=f'https://zarplata.ru/search/vacancy?L_save_area=true&text=&excluded_text=&area=7232&area=1217&'
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
                    url=f'https://zarplata.ru/vacancy/{vacancy_id}/contacts?employerId={employer_id}',
                    timeout=ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return dict()
        except Exception as exception:
            print(repr(exception))
            await asyncio.sleep(30)


async def parse_region_page(area_id: str, role_id: str, page: int, sort_type: str) -> dict:
    while True:
        async with ClientSession(headers=get_headers(index=2), connector=TCPConnector(ssl=False)) as session:
            try:
                async with session.get(
                        url='https://zarplata.ru/search/vacancy?'
                        'L_save_area=true&'
                        'text=&'
                        'excluded_text=&'
                        f'professional_role={role_id}&'
                        f'area={area_id}&'
                        'salary=&'
                        'currency_code=RUR&'
                        'experience=doesNotMatter&'
                        f'order_by={sort_type}&'
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
                    url='https://zarplata.ru/search/vacancy/advanced?hhtmFrom=main',
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
