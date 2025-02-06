import os
import asyncio
import random
import json

from tqdm import tqdm
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from colorama import Fore
from itertools import count


async def main() -> None:
    while True:
        catalogue = await get_catalogue()
        for city_id, city_name, role_id, role_name in set(catalogue):
            file_vacancies, new_vacancies = await get_file_vacancies(), set()
            print(f'На данный момент в хранилище {len(file_vacancies)} вакансий')
            try:
                for offset in count(start=40, step=40):
                    print(f'Парсим вакансии: Россия / {city_name} / {role_name}. Страница {offset // 40}')
                    page_vacancies = await parse_search_page(city_id, role_id, offset - 40)
                    if edit_vacancies := format_vacancies(page_vacancies):
                        new_vacancies = await send_vacancies(
                            vacancies=edit_vacancies,
                            file_vacancies=file_vacancies,
                            new_vacancies=new_vacancies,
                            city=city_name
                        )
                        await upload_vacancies(file_vacancies | new_vacancies)
                        await asyncio.sleep(2)
                    else:
                        break
            except Exception as exception:
                print(Fore.RED + repr(exception))
                await asyncio.sleep(120)


async def get_catalogue() -> list[tuple[str, str, str, str]]:
    result = list()
    async with ClientSession(headers=await get_headers(index=1), connector=TCPConnector(ssl=False)) as session:
        roles, regions = await parse_roles(session), await parse_regions(session)
        roles, regions = format_roles(roles), format_regions(regions)
        for region_id, region_name in regions.items():
            for role_id, role_name in roles.items():
                if role_name:
                    result.append((region_id, region_name, role_id, role_name))
        else:
            return result


def format_vacancies(vacancies: dict) -> dict:
    result = dict()
    for vacancy in vacancies.get('data', list()):
        result[vacancy.get('id')] = dict()
    else:
        for row in vacancies.get('included', list()):
            if row.get('id') in result:
                result[row.get('id')][row.get('type')] = row
        else:
            return result


def format_roles(roles: dict) -> dict[str, str]:
    result = dict()
    for main_label in roles.get('data', dict()):
        for label in main_label.get('relationships', dict()).get('subCatalogues', dict()).get('data', dict()):
            result[label.get('id')] = None
    else:
        for row in roles.get('included', dict()):
            if row.get('id') in result:
                result[row.get('id')] = row.get('attributes', dict()).get('label')
        else:
            return result


def format_regions(regions: dict) -> dict[str, str]:
    if main_region := tuple(
        region.get('id') for region in regions.get('included', dict()) if
        region.get('type') == 'country' and region.get('attributes', dict()).get('name') == 'Россия'
    ):
        result, (main_id, *_) = dict(), main_region
        for region in regions.get('included', dict()):
            if region.get('relationships', dict()).get('country', dict()).get('data', dict()).get('id') == main_id:
                result[region.get('id')] = region.get('attributes', dict()).get('name')
        else:
            return result
    else:
        return dict()
# https://www.superjob.ru/vacancy/search/?catalogues[0]=464&geo[t][0]=1160&page=1


async def send_vacancies(vacancies: dict[str, dict], file_vacancies: set, new_vacancies: set, city: str) -> set:
    async with ClientSession(headers=await get_headers(index=3), connector=TCPConnector(ssl=False)) as session:
        for vacancy_id, data in tqdm(vacancies.items(), desc='Отправка вакансий по запросу'):
            if vacancy_id not in file_vacancies and vacancy_id not in new_vacancies:
                if not data['vacancyContactInfo']['attributes']['isContactPersonHidden']:
                    data |= {'vacancyId': vacancy_id, 'cityName': city}
                    # if contacts := await parse_contacts(session, vacancy['vacancyId'], employer_id):
                    first_url, first_data = await format_vacancy(data, index=1)
                    second_url, second_data = await format_vacancy(data, index=2)
                    for url, body in zip((first_url, second_url), (first_data, second_data)):
                        await send_webhook(url, body)
                    else:
                        new_vacancies.add(vacancy_id)
                    # else:
                    #     await asyncio.sleep(random.random() * 5)
        else:
            return new_vacancies


async def format_vacancy(vacancy: dict, index: int) -> tuple[str, dict]:
    phone = None
    if phones := vacancy.get('phones', dict()).get('phones'):
        for phone_data in phones:
            phone = f'+{phone_data["country"]}{phone_data["city"]}{phone_data["number"]}'
            break
    if index == 1:
        url = 'https://cloud.roistat.com/integration/webhook?key=a58c86c38a259de63562d533d7c7edf4'
        return url, {
            'city': vacancy.get("cityName"),
            'company_name': vacancy.get('vacancyCompanyInfo', dict()).get('attributes', dict()).get('name'),
            'vacancy_url': f'https://www.superjob.ru/vakansii/{vacancy.get("vacancyId")}.html',
            'title': vacancy.get('vacancyMainInfo', dict()).get('attributes', dict()).get('profession'),
            'name': dict.get(vacancy, 'fio'),
            "email": dict.get(vacancy, 'email'),
            "phone": phone,
            "comment": f'https://www.superjob.ru/vakansii/{vacancy.get("vacancyId")}.html',
            "roistat_visit": 'superjob.ru',
            "fields": {"site": "superjob.ru", "source": "superjob.ru", "promocode": None}
        }
    else:
        url = 'https://c6ce863bb1eb.vps.myjino.ru/contacts?apiKey=Wy7RXAzSRZpD4a3q'
        return url, {
            'vacancy_name': vacancy.get('vacancyMainInfo', dict()).get('attributes', dict()).get('profession'),
            'city': vacancy.get("cityName"),
            'company_name': vacancy.get('vacancyCompanyInfo', dict()).get('attributes', dict()).get('name'),
            'vacancy_url': f'https://www.superjob.ru/vakansii/{vacancy.get("vacancyId")}.html',
            "source": "superjob.ru",
            "name": dict.get(vacancy, 'fio'),
            "email": dict.get(vacancy, 'email'),
            "phone": phone,
            "data": (
                f"{vacancy.get('vacancyMainInfo', dict()).get('attributes', dict()).get('profession')};"
                f"{vacancy.get('vacancyCompanyInfo', dict()).get('attributes', dict()).get('name')};"
                f"https://www.superjob.ru/vakansii/{vacancy.get('vacancyId')}.html';"
                f"{dict.get(vacancy, 'fio')};"
                f"{dict.get(vacancy, 'email')};"
                f"{phone};"
                f"{vacancy.get('cityName')}"
            )
        }


async def get_headers(index: int) -> dict:
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
            'x-static-version': '',
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


async def get_file_vacancies() -> set[int]:
    filename, vacancies = r'./VacanciesSuperJobRU.json', set()
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
    async with ClientSession(headers=await get_headers(index=1), connector=TCPConnector(ssl=False)) as session:
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


async def parse_search_page(area_id: str, role_id: str, offset: int) -> dict:
    params, tries = {
        "page[limit]": 40, "page[offset]": offset,
        "include": (
            "mainInfo.salary.salaryPeriod,detailInfo[workType,externalResponse],vacancyMetroStations[station.lines,"
            "timeToMetro],company[reviewScore,logo,opf],companyInfo,contactInfo,searchHighlights,searchSnippet."
            "searchSnippetSections[searchHighlight,vacancySearchSnippetSectionType],requiredExperience,"
            "brandingSnippet.images.image.file.attachInfo,beFirstLabel,vacancyOfTheDay,vacancyTags,"
            "searchDiscardedKeywords,watch,survey.questions.answers,chatAvailable,inAnotherCityLabel,"
            "vacancyAdditionalFlags,geoScopes.scopeType,town,searchTypeScope,company.countOfEmployee,company.groups,"
            "companyLink,favoriteVacancy,hrInfo.campaigns.campaignType,hrInfo.campaigns.campaignStatus,trudVsem,"
            "trudVsem.state,trudVsem.action,userSurveyAnswer.answers,clusterCounter,blockage,complaint,company.blockage"
        ),
        "filters[forceRemoteWork]": 1,
        "filters[allowSimilarPaymentSupplement]": 1,
        "filters[adaptableKeywords]": 1,
        "filters[allowRussiaTownSupplement]": 1,
        "filters[town]": int(area_id),
        "filters[catalogues]": role_id,
        "filters[withoutResumeSendOnVacancy]": 1,
        "filters[domain]": 700,
        "fields[vacancyMainInfo]": "profession,updatedAt",
        "fields[complaint]": "",
        "fields[vacancyStatusesInfo]": "isArchive",
        "fields[vacancyTagType]": "key,label",
        "fields[address]": "cityName",
        "fields[vacancyDetailInfo]": "isResumeRequired,isRemoteWork,isCallCatching,isBeneficial",
        "fields[company]": "title",
        "fields[reviewScore]": "generalScore",
        "fields[vacancyCompanyInfo]": "name,isAnonymous",
        "fields[town]": "name"
    }, 5
    while True:
        async with ClientSession(headers=await get_headers(index=2), connector=TCPConnector(ssl=False)) as session:
            try:
                async with session.get(
                        url='https://www.superjob.ru/jsapi3/0.1/vacancy/',
                        params=params,
                        timeout=ClientTimeout(total=30)
                ) as response:
                    tries -= 1
                    if response.status == 200:
                        return await response.json()
                    else:
                        if tries:
                            await asyncio.sleep(10)
                        else:
                            return dict()
            except:
                tries -= 1
                if tries:
                    await asyncio.sleep(10)
                else:
                    return dict()


async def parse_roles(session: ClientSession) -> dict:
    params, tries = {"page[limit]": 15, "page[offset]": 0}, 5
    while True:
        try:
            async with session.get(
                    url='https://www.superjob.ru/jsapi3/0.1/catalogue/',
                    params=params,
                    timeout=ClientTimeout(total=30)
            ) as response:
                tries -= 1
                if response.status == 200:
                    return await response.json()
                else:
                    if tries:
                        await asyncio.sleep(30)
                    else:
                        return dict()
        except:
            tries -= 1
            if tries:
                await asyncio.sleep(30)
            else:
                return dict()


async def parse_regions(session: ClientSession) -> dict:
    params, tries = {
        "include": (
            "country,region.country,subject.country,subject.region,town[subject,country,landingInfo],"
            "town.subject.region,domain.domainType"
        ),
        "filters[type]": "country,subject,town,region", "filters[domain]": "700"
    }, 5
    while True:
        try:
            async with session.get(
                    url='https://www.superjob.ru/jsapi3/0.1/geo/',
                    params=params,
                    timeout=ClientTimeout(total=30)
            ) as response:
                tries -= 1
                if response.status == 200:
                    return await response.json()
                else:
                    if tries:
                        await asyncio.sleep(30)
                    else:
                        return dict()
        except:
            tries -= 1
            if tries:
                await asyncio.sleep(30)
            else:
                return dict()


if __name__ == '__main__':
    asyncio.run(main())
