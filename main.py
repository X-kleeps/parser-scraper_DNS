import pickle
import re
import sys
from dotenv import dotenv_values  # Используется для загрузки переменных окружения из .env файла.
from random import randint  # Используется для генерации случайных значений, в частности для пауз.
from time import sleep as pause  # Переименовывает sleep в pause для удобства использования.
from time import time  # Используется для замера времени выполнения программы.

from bs4 import BeautifulSoup  # Библиотека для парсинга HTML и извлечения данных.
from psycopg2 import connect  # Библиотека для работы с PostgreSQL базами данных.
from selenium.webdriver import Chrome  # WebDriver для автоматизации браузера Chrome.
from selenium.webdriver.chrome.service import Service  # Для работы с WebDriver как с сервисом.
from selenium.webdriver.common.by import By  # Упрощает поиск элементов на странице.
from tqdm import tqdm  # Прогресс-бар для итераций.
from webdriver_manager.chrome import ChromeDriverManager  # Автоматически управляет установкой и обновлением драйвера Chrome.

from converter import *  # Импортируем конвертер для работы с данными (предположительно для сохранения в разные форматы).

# Функция для вставки данных в PostgreSQL базу данных.
def to_postgresql_database(data: Iterable[Mapping[str, Any]],
                           table_name: str,
                           host: str, user: str,
                           password: str, database: str) -> None:
    """
    Создаёт SQL таблицу в базе данных PostgreSQL из итерируемого объекта (data) 
    и добавляет данные в таблицу с именем table_name.
    """
    # Преобразование имени таблицы в нижний регистр и замена пробелов на подчеркивания.
    table_name = table_name.lower().replace(' ', '_')

    with connect(host=host, user=user, password=password, database=database) as connection:
        connection.autocommit = True  # Автоматическое сохранение изменений в базе данных.

        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {table_name};"  # Удаляем таблицу, если она уже существует.
            )

            # Создание новой таблицы с необходимыми полями.
            cursor.execute(
                f"""CREATE TABLE {table_name}
                (id                    INT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                manufacturer           VARCHAR(20)  NOT NULL,
                model                  VARCHAR(60)  NOT NULL,
                price                  INT          NOT NULL,
                price_without_discount INT          NOT NULL,
                discount               INT          NOT NULL,
                cpu                    VARCHAR(50)  NOT NULL,
                discrete_graphics_card  VARCHAR(60) NOT NULL,
                integrated_graphics    VARCHAR(30)  NOT NULL,
                ram                    VARCHAR(30)  NOT NULL,
                ssd                    VARCHAR(30)  NOT NULL,
                hdd                    VARCHAR(40)  NOT NULL,
                screen                 VARCHAR(50)  NOT NULL,
                operating_system       VARCHAR(50)  NOT NULL,
                url                    text         NOT NULL);"""
            )

            # Вставляем данные по каждому ноутбуку в таблицу.
            for notebook in data:
                cursor.execute(
                    f"""INSERT INTO gaming_notebooks VALUES 
                    (DEFAULT,
                    '{notebook["Производитель"]}',
                    '{notebook["Модель"]}',
                    {notebook["Цена"]},
                    {notebook["Цена без скидки"]},
                    {notebook["Скидка"]},
                    '{notebook["Процессор"]}',
                    '{notebook["Дискретная видеокарта"]}',
                    '{notebook["Встроенная видеокарта"]}',
                    '{notebook["Оперативная память"]}',
                    '{notebook["SSD"]}',
                    '{notebook["HDD"]}',
                    '{notebook["Экран"]}',
                    '{notebook["Операционная система"]}',
                    '{notebook["Ссылка"]}')"""
                )


# Функция для получения всех ссылок на ноутбуки с нескольких страниц.
def get_all_notebook_urls(driver) -> list[str]:
    """
    Собирает все ссылки на ноутбуки с нескольких страниц сайта.
    """
    page = 1
    url_template = 'https://www.dns-shop.ru/catalog/17a892f816404e77/noutbuki/?f[p3q]=b3ci&p={page}'

    url = url_template.format(page=page)
    driver.get(url=url)  # Открытие первой страницы.
    pause(10)

    set_city(driver, 'Краснодар')  # Устанавливаем город.

    urls = []
    # Получаем ссылки с каждой страницы до тех пор, пока они доступны.
    while page_urls := get_urls_from_page(driver):
        print(f'Страница {page}')
        urls.extend(page_urls)
        url = url_template.format(page=page)
        page += 1
        driver.get(url)
        pause(randint(6, 9))  # Пауза между запросами для имитации поведения пользователя.
    return urls


# Функция для установки города на сайте.
def set_city(driver, city: str) -> None:
    """
    Устанавливает указанный город на сайте.
    """
    pause(7)  # Пауза для загрузки страницы.
    driver.find_element(By.CLASS_NAME, "header-top-menu__common-link.header-top-menu__common-link_city").click()
    pause(7)
    city_input = driver.find_element(By.CLASS_NAME, 'base-ui-input-search__input')
    city_input.clear()  # Очищает поле для ввода.
    city_input.send_keys(city)  # Вводит название города.
    pause(1)
    driver.find_element(By.CSS_SELECTOR, 'ul.cities-search > li').click()  # Выбирает город из списка.
    pause(10)


# Функция для получения всех ссылок на ноутбуки с текущей страницы.
def get_urls_from_page(driver) -> list[str]:
    """
    Собирает все ссылки на ноутбуки с текущей страницы.
    """
    soup = BeautifulSoup(driver.page_source, 'lxml')
    elements = soup.find_all('a', class_="catalog-product__name ui-link ui-link_black")  # Ищет ссылки на ноутбуки.
    return list(map(lambda element: 'https://www.dns-shop.ru' + element.get("href") + 'characteristics/', elements))


# Функция для получения данных о конкретном ноутбуке.
def get_notebook_data(driver, url: str) -> dict[str, str | int]:
    """
    Собирает информацию о ноутбуке по переданной ссылке.
    """
    notebook = dict()
    driver.get(url)  # Переход на страницу ноутбука.
    pause(5)

    soup = BeautifulSoup(driver.page_source, 'lxml')

    # Извлечение данных о модели.
    model = find_if_on_page(r'Модель', soup)
    notebook["Производитель"], notebook["Модель"] = re.search(r"(Dream Machines|.+?) (.+)", model).group(1, 2)

    notebook["Операционная система"] = find_if_on_page(r'Операционная система', soup)

    # Извлечение информации о экране.
    screen_type = find_if_on_page(r'Тип экрана', soup)
    screen_diagonal = find_if_on_page(r'Диагональ экрана \(дюйм\)', soup)
    screen_resolution = re.search(r'(\d+x\d+)', find_if_on_page(r'Разрешение экрана', soup)).group(1)
    max_screen_refresh_rate = find_if_on_page(r'Максимальная частота обновления экрана', soup)
    notebook["Экран"] = f"{screen_resolution} {screen_diagonal} {screen_type} {max_screen_refresh_rate}"

    # Извлечение данных о процессоре.
    cpu_model = find_if_on_page(r'Модель процессора', soup)
    number_of_performance_cores = find_if_on_page(r'Количество производительных ядер', soup)
    cpu_frequency = find_if_on_page(r'Частота процессора', soup)
    if cpu_frequency != 'Нет':
        notebook["Процессор"] = f"{cpu_model} {number_of_performance_cores}x{cpu_frequency}"
    else:
        notebook["Процессор"] = f"{cpu_model} кол-во ядер: {number_of_performance_cores}"

    # Данные о RAM.
    ram_type = find_if_on_page(r'Тип оперативной памяти', soup)
    amount_of_ram = find_if_on_page(r'Объем оперативной памяти', soup)
    ram_frequency = find_if_on_page(r'Частота оперативной памяти', soup)
    if ram_frequency != 'Нет':
        notebook["Оперативная память"] = f"{amount_of_ram} {ram_type} {ram_frequency}"
    else:
        notebook["Оперативная память"] = f"{amount_of_ram} {ram_type}"

    notebook["Встроенная видеокарта"] = find_if_on_page(r'Модель встроенной видеокарты', soup)

    # Данные о дискретной видеокарте.
    built_in_video_card_model = find_if_on_page(r'Модель дискретной видеокарты', soup)
    video_chip_manufacturer = find_if_on_page(r'Производитель видеочипа', soup)
    video_memory_size = find_if_on_page(r'Объем видеопамяти', soup)
    notebook["Дискретная видеокарта"] = f"{video_chip_manufacturer} {built_in_video_card_model} {video_memory_size}"

    # Данные о SSD и HDD.
    total_ssd_size = find_if_on_page(r'Общий объем твердотельных накопителей \(SSD\)', soup)
    ssd_disk_type = find_if_on_page(r'Тип SSD диска', soup)
    notebook["SSD"] = f"{total_ssd_size} {ssd_disk_type}"

    notebook["HDD"] = find_if_on_page(r'Общий объем жестких дисков (HDD)', soup).capitalize()

    count = 0
    while True:
        soup = BeautifulSoup(driver.page_source, 'lxml')
        # Извлечение цены и скидки, если доступно.
        if old_price_element := soup.find('span', class_='product-buy__prev'):
            notebook["Цена"], notebook["Цена без скидки"] = map(
                int, soup.find('div', class_='product-buy__price product-buy__price_active').text.replace(' ', '').split('₽')
            )
            notebook["Цена без скидки"] = int(old_price_element.text.replace(' ', ''))
            notebook["Скидка"] = round(100 - (notebook["Цена"] / notebook["Цена без скидки"]) * 100)
            break
        elif price := soup.find('div', class_='product-buy__price'):
            notebook["Цена"] = int(price.text.replace(' ', '')[:-1])
            notebook["Цена без скидки"], notebook["Скидка"] = 0, 0
            break
        else:
            count += 1
            pause(1)
    notebook["Ссылка"] = url

    return notebook


# Функция для поиска и извлечения данных с помощью регулярных выражений.
def find_if_on_page(regex: str, soup) -> str:
    """
    Проверяет, есть ли элемент на странице, и если да,
    возвращает текст следующего div.
    """
    if (element := soup.find(text=re.compile(fr"^ ?{regex} ?$"))) is not None:
        return element.find_next("div").text.strip()
    else:
        return "Нет"


# Основная функция программы.
def main():
    start_time = time()  # Замер времени начала выполнения программы.
    with Chrome(service=Service(ChromeDriverManager().install())) as driver:
        driver.maximize_window()

        print("Получение списка всех ссылок на игровые ноутбуки:")
        urls = get_all_notebook_urls(driver)  # Получение всех ссылок на ноутбуки.
        with open('urls.txt', 'w') as file:
            file.write('\n'.join(urls))

        print("Получение характеристик всех игровых ноутбуков:")
        with open('urls.txt', 'r') as file:
            urls = list(map(lambda line: line.strip(), file.readlines()))

        notebooks = []
        for url in tqdm(urls, ncols=70, unit='notebook', colour='green', file=sys.stdout):
            notebooks.append(get_notebook_data(driver, url))  # Получение данных для каждого ноутбука.

    # Сохранение данных в разных форматах.
    with open('notebooks_list_pickle.txt', 'wb+') as file:
        pickle.dump(notebooks, file)

    with open('notebooks_list_pickle.txt', 'rb') as file:
        notebooks = pickle.load(file)

    column_names = [
        'Производитель', 'Модель', 'Цена', 'Цена без скидки', 'Скидка',
        'Процессор', 'Дискретная видеокарта', 'Встроенная видеокарта',
        'Оперативная память', 'SSD', 'HDD', 'Экран', 'Операционная система', 'Ссылка'
    ]

    # Сохранение в Excel, JSON, XML и CSV.
    to_excel(notebooks, column_names, file_name="notebooks")
    to_json(notebooks, file_name="notebooks")
    to_xml(notebooks, parameters=column_names, root='Ноутбуки', item_name='Ноутбук', file_name="notebooks")
    to_csv(notebooks, column_names, file_name="notebooks")

    # Загрузка данных в PostgreSQL базу данных.
    config = dotenv_values(".env")
    to_postgresql_database(
        notebooks, "Gaming notebooks",
        host=config['HOST'], user=config['USER_NAME'],
        password=config['PASSWORD'], database=config['DB_NAME']
    )

    # Подсчёт времени выполнения программы.
    total_time = time() - start_time
    print(f"Время выполнения:\n"
          f"{(total_time // 3600):02.0f}:"
          f"{(total_time % 3600 // 60):02.0f}:"
          f"{(total_time % 60):02.0f}")


if __name__ == '__main__':
    main()