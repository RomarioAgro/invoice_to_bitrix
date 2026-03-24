import openpyxl
import dateparser
from typing import List, Dict
import re

def make_list_from_xlsx(file_path: str = '') -> List:
    """
    разбираем xlsx в список, а потом уже в списке будем искать все что надо
    :return:
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet = wb.active
    all_cell = []
    for row in sheet.iter_rows(values_only=True):
        for cell in row:
            if not isinstance(cell, str):
                continue
            text = cell.lower()
            all_cell.append(text)
    return all_cell


def parse_invoice(in_list: List = None) -> Dict:
    """
    идем по списку и собираем данные в словарь
    :param in_list:
    :return:
    """
    data = {
        "invoice_number": None,
        "invoice_date": None,
        "executor_inn": None,
        "total_amount": None
    }
    for i, text in enumerate(in_list):
            # 1. Номер счета
            if "счет" in text and "№" in text:
                match = re.search(r'№\s*([^\s]+)', text)
                if match:
                    data["invoice_number"] = match.group(1).upper()
            # 2. Дата счета
                match = re.search(r"от\s+(\d{1,2}\s+[а-яА-ЯёЁ]+\s+\d{4})\s*г\.", text)
                if match:
                    date_obj = dateparser.parse(match.group(1))
                    data["invoice_date"] = date_obj.strftime("%d.%m.%Y")

            # 3. Название заказчика
            if "заказчик" in text:
                # предполагаем, что название после ":"
                pattern = r'\bинн\s*([0-9]{10,12})\b'
                match = re.search(pattern, in_list[i + 1])
                if match:
                    data["customer_inn"] = match.group(1)

            # 4. ИНН исполнителя
            if "исполнител" in text:
                pattern = r'\bинн\s*([0-9]{10,12})\b'
                match = re.search(pattern, in_list[i + 1])
                if match:
                    data["executor_inn"] = match.group(1)

            # 5. Сумма счета
            if "сумм" in text:
                match = re.search(r'на сумму\s*([\d\s]+,\d{2})', text)
                if match:
                    clean = match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
                    data["total_amount"] = clean
    return data


if __name__ == "__main__":
    file_path = "Счет на оплату № ЦТ-1934 ЮВС точка доступа.xlsx"

    list_of_invoice = make_list_from_xlsx(file_path)
    data_of_invoice = parse_invoice(list_of_invoice)
    print(data_of_invoice)