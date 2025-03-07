import os
import re
import time
import logging
import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import concurrent.futures
import threading

from ..utils.config import config
from ..utils.logger import get_logger
from ..utils.memory_manager import MemoryManager

# 로거 설정
logger = get_logger()

class KSMROCrawler:
    """KSMRO 웹사이트 전용 크롤러"""
    
    def __init__(self, max_workers=None, base_url=None):
        self.base_url = base_url or config.crawler.base_url
        self.max_workers = max_workers or config.processing.max_workers
        self.memory_manager = MemoryManager(config.processing.memory_limit)
        
        # 세션 설정 개선
        self.session = requests.Session()
        self.session.headers.update(config.crawler.headers)
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=self.max_workers,
            pool_maxsize=self.max_workers * 2,
            max_retries=3
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        self.found_product_ids = set()
        self.visited_urls = set()
        self.chrome_options = self._setup_chrome_options()
        self.driver = None
        self.driver_lock = threading.RLock()  # 드라이버 접근을 위한 락 추가
        
    def _setup_chrome_options(self):
        """Chrome 웹드라이버 옵션 설정"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-infobars")
        return chrome_options
    
    def _init_selenium(self):
        """Selenium 드라이버 초기화 (필요할 때만)"""
        with self.driver_lock:
            if self.driver is None:
                try:
                    self.driver = webdriver.Chrome(options=self.chrome_options)
                    logger.info("Selenium 드라이버 초기화 완료")
                except Exception as e:
                    logger.error(f"Selenium 드라이버 초기화 실패: {str(e)}")
                    raise
    
    def _close_selenium(self):
        """Selenium 드라이버 종료"""
        with self.driver_lock:
            if self.driver:
                try:
                    self.driver.quit()
                    logger.debug("Selenium 드라이버 종료 완료")
                except Exception as e:
                    logger.error(f"Selenium 드라이버 종료 실패: {str(e)}")
                finally:
                    self.driver = None
    
    def get_product_details(self, product_url):
        """상품 상세 페이지 크롤링 (유효성 검사 추가)"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(product_url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 메타 태그에서 안전하게 정보 추출 (없으면 기본값 설정)
            product_name_tag = soup.find("meta", property="og:title")
            product_image_tag = soup.find("meta", property="og:image")
            product_description_tag = soup.find("meta", property="og:description")

            product_name = product_name_tag["content"].strip() if product_name_tag else ""
            product_image = product_image_tag["content"].strip() if product_image_tag else ""
            product_description = product_description_tag["content"].strip() if product_description_tag else ""

            # 상품 가격 추출 (페이지 내 특정 요소에서 추출, 예시)
            price_element = soup.select_one(".price_box .price strong")
            product_price = price_element.get_text(strip=True) if price_element else ""

            # 상품 스펙 추출 (없으면 빈 딕셔너리)
            specs = {}
            spec_rows = soup.select(".vi_txt_li dl")
            for row in spec_rows:
                dt = row.select_one("dt")
                dd = row.select_one("dd")
                if dt and dd:
                    specs[dt.get_text(strip=True)] = dd.get_text(strip=True)

            # 이미지 목록 추출 (없으면 빈 리스트)
            images = [product_image] if product_image else []

            # 상품 정보 유효성 검사 추가
            if not product_name or product_name == "상품명 정보 없음":
                logger.warning(f"상품 정보가 유효하지 않아 크롤링을 건너뜁니다: {product_url}")
                return None

            product_details = {
                "url": product_url,
                "name": product_name,
                "image": product_image,
                "description": product_description,
                "price": product_price,
                "specs": specs,
                "images": images
            }

            logger.info(f"상품 크롤링 성공: {product_url}")
            return product_details

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP 요청 실패: {product_url} - {str(e)}")
        except Exception as e:
            logger.error(f"상품 크롤링 중 오류: {product_url} - {str(e)}")

        return None
    
    def _extract_title(self, soup):
        """상품 제목 추출"""
        title_elem = soup.select_one('h3.item_detail')
        if title_elem:
            return title_elem.text.strip()
        
        # 대체 방법
        title_elem = soup.select_one('.sit_title')
        if title_elem:
            return title_elem.text.strip()
            
        return "제목 없음"
    
    def _extract_price(self, soup):
        """상품 가격 추출"""
        price_elem = soup.select_one('.price .mpr')
        if price_elem:
            price_text = price_elem.text.strip()
            # 숫자만 추출
            price = re.sub(r'[^\d]', '', price_text)
            return price
        return "가격 정보 없음"
    
    def _extract_specs(self, soup):
        """상품 스펙 정보 추출"""
        specs = {}
        
        # 상품정보제공고시 테이블에서 정보 추출
        spec_table = soup.select_one('.tbl_frm01 table')
        if spec_table:
            rows = spec_table.select('tr')
            for row in rows:
                th = row.select_one('th')
                td = row.select_one('td')
                if th and td:
                    key = th.text.strip()
                    value = td.text.strip()
                    specs[key] = value
        
        # 상품 옵션 정보
        option_elems = soup.select('.sit_option th, .sit_option td')
        for i in range(0, len(option_elems), 2):
            if i+1 < len(option_elems):
                key = option_elems[i].text.strip()
                value = option_elems[i+1].text.strip()
                specs[key] = value
                
        return specs
    
    def _extract_description(self, soup):
        """상품 상세 설명 추출"""
        desc_elem = soup.select_one('.ofh.tac.padt10.padb10')
        if desc_elem:
            return desc_elem.text.strip()
        
        # 대체 방법
        desc_elem = soup.select_one('#sit_inf_explan')
        if desc_elem:
            return desc_elem.text.strip()
            
        return "상세 설명 없음"
    
    def _extract_images(self, soup, base_url):
        """상품 이미지 URL 추출"""
        image_urls = []
        
        # 메인 이미지
        main_img = soup.select_one('#sit_pvi_big img')
        if main_img and main_img.get('src'):
            img_url = urljoin(base_url, main_img['src'])
            image_urls.append(img_url)
        
        # 추가 이미지들
        extra_imgs = soup.select('.sit_pvi_thumb img')
        for img in extra_imgs:
            if img.get('src'):
                img_url = urljoin(base_url, img['src'])
                image_urls.append(img_url)
        
        # 상세 설명 내 이미지
        desc_imgs = soup.select('.ofh.tac.padt10.padb10 img')
        for img in desc_imgs:
            if img.get('src'):
                img_url = urljoin(base_url, img['src'])
                image_urls.append(img_url)
                
        return image_urls
    
    def _extract_category(self, soup):
        """상품 카테고리 추출"""
        try:
            # 카테고리 경로 추출
            category_elem = soup.select_one('.sct_here')
            if category_elem:
                return category_elem.text.strip()
            
            # 대체 방법
            breadcrumb = soup.select('.sct_here a')
            if breadcrumb:
                return ' > '.join([a.text.strip() for a in breadcrumb])
            
        except Exception as e:
            logger.debug(f"카테고리 추출 중 오류: {str(e)}")
        
        return "카테고리 정보 없음"
    
    def crawl_category(self, category_url, max_pages=5):
        """카테고리 페이지 크롤링"""
        product_urls = []
        
        try:
            logger.info(f"카테고리 크롤링 시작: {category_url}")
            self._init_selenium()
            
            for page in range(1, max_pages + 1):
                page_url = f"{category_url}&page={page}" if '?' in category_url else f"{category_url}?page={page}"
                
                retry_count = 0
                max_retries = 3
                while retry_count < max_retries:
                    try:
                        self.driver.get(page_url)
                        WebDriverWait(self.driver, 20).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".pr_desc a, .sct_txt a"))
                        )
                        
                        # 상품 링크 추출
                        product_links = self.driver.find_elements(By.CSS_SELECTOR, ".pr_desc a[href*='view.php?index_no='], .sct_txt a[href*='view.php?index_no=']")
                        
                        if not product_links:
                            logger.info(f"더 이상 상품이 없습니다. 페이지: {page}")
                            break
                        
                        for link in product_links:
                            product_url = link.get_attribute('href')
                            if product_url and product_url not in self.visited_urls:
                                product_urls.append(product_url)
                                self.visited_urls.add(product_url)
                        
                        logger.info(f"카테고리 페이지 {page} 크롤링 완료, {len(product_links)}개 상품 발견")
                        
                        # 과도한 요청 방지를 위한 딜레이 추가
                        time.sleep(2)
                        
                        # 성공적으로 처리되었으므로 retry 루프 탈출
                        break
                        
                    except TimeoutException:
                        retry_count += 1
                        logger.warning(f"페이지 로딩 타임아웃 ({retry_count}/{max_retries}): {page_url}")
                        time.sleep(3)  # 재시도 전 대기
                        if retry_count >= max_retries:
                            logger.error(f"최대 재시도 횟수 초과로 페이지 크롤링 실패: {page_url}")
                            break
                    except Exception as e:
                        retry_count += 1
                        logger.error(f"페이지 크롤링 중 오류 ({retry_count}/{max_retries}): {page_url} - {str(e)}")
                        time.sleep(3)
                        if retry_count >= max_retries:
                            logger.error(f"최대 재시도 횟수 초과로 페이지 크롤링 실패: {page_url}")
                            break
        
        except Exception as e:
            logger.error(f"카테고리 크롤링 중 오류: {str(e)}")
        
        return product_urls
    
    def search_products(self, keyword, max_pages=5):
        """키워드로 상품 검색"""
        search_url = f"{self.base_url}/shop/search.php?ss_tx={keyword}"
        return self.crawl_category(search_url, max_pages)
    
    def crawl_product_ids(self, id_range):
        """ID 범위로 상품 크롤링"""
        product_urls = []
        start_id, end_id = map(int, id_range.split('-'))
        
        logger.info(f"ID 범위 {start_id}-{end_id}로 상품 크롤링 시작")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for product_id in range(start_id, end_id + 1):
                product_url = f"{self.base_url}/shop/view.php?index_no={product_id}"
                futures.append(executor.submit(self._check_product_exists, product_url, product_id))
            
            for future in futures:
                result = future.result()
                if result:
                    product_urls.append(result)
        
        logger.info(f"ID 범위 크롤링 완료, {len(product_urls)}개 유효한 상품 발견")
        return product_urls
    
    def _check_product_exists(self, url, product_id):
        """상품 URL이 유효한지 확인"""
        try:
            response = self.session.get(url, timeout=config.crawler.timeout)
            if response.status_code == 200 and "item_detail" in response.text:
                self.found_product_ids.add(str(product_id))
                logger.debug(f"유효한 상품 ID 발견: {product_id}")
                return url
        except Exception as e:
            logger.debug(f"상품 ID {product_id} 확인 중 오류: {str(e)}")
        return None
    
    def download_image(self, image_url, save_path):
        """이미지 다운로드"""
        try:
            response = self.session.get(image_url, stream=True, timeout=config.crawler.timeout)
            if response.status_code == 200:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                return True
            else:
                logger.warning(f"이미지 다운로드 실패: {image_url}, 상태 코드: {response.status_code}")
        except Exception as e:
            logger.error(f"이미지 다운로드 중 오류: {str(e)}")
        return False
    
    def export_product_ids(self, output_path="found_product_ids.txt"):
        """발견된 상품 ID 내보내기"""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(list(self.found_product_ids), f, ensure_ascii=False)
            logger.info(f"{len(self.found_product_ids)}개의 상품 ID를 {output_path}에 저장했습니다.")
        except Exception as e:
            logger.error(f"상품 ID 내보내기 실패: {str(e)}")
    
    def __enter__(self):
        """컨텍스트 매니저 진입"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        self._close_selenium()
        if self.session:
            self.session.close()

    def generate_product_urls(self, id_patterns=None, start_id=None, end_id=None, scan_all_categories=False):
        """
        상품 URL 생성
        
        Args:
            id_patterns: ID 패턴 목록 (예: ['102XXXXX', '103XXXXX'])
            start_id: ID 범위 시작
            end_id: ID 범위 끝
            scan_all_categories: 모든 카테고리 스캔 여부
            
        Returns:
            생성된 상품 URL 목록
        """
        product_urls = []
        
        # 1. ID 패턴 기반 URL 생성
        if id_patterns:
            logger.info(f"ID 패턴 기반 URL 생성 중...")
            for pattern in id_patterns:
                if 'X' in pattern:
                    # X가 있는 위치 찾기
                    x_positions = [i for i, char in enumerate(pattern) if char == 'X']
                    
                    # X 개수에 따라 전략 조정
                    if len(x_positions) > 4:  # X가 너무 많으면 랜덤 샘플링
                        import random
                        for _ in range(1000):  # 최대 1000개 ID 생성
                            id_copy = list(pattern)
                            for pos in x_positions:
                                id_copy[pos] = random.choice('0123456789')
                            product_id = ''.join(id_copy)
                            product_url = f"{self.base_url}/shop/view.php?index_no={product_id}"
                            product_urls.append(product_url)
                    else:
                        # 모든 가능한 조합 생성
                        import itertools
                        for digits in itertools.product('0123456789', repeat=len(x_positions)):
                            id_copy = list(pattern)
                            for i, pos in enumerate(x_positions):
                                id_copy[pos] = digits[i]
                            product_id = ''.join(id_copy)
                            product_url = f"{self.base_url}/shop/view.php?index_no={product_id}"
                            product_urls.append(product_url)
                else:
                    # X가 없는 경우 그대로 사용
                    product_url = f"{self.base_url}/shop/view.php?index_no={pattern}"
                    product_urls.append(product_url)
        
        # 2. ID 범위 기반 URL 생성
        elif start_id and end_id:
            logger.info(f"ID 범위 {start_id}-{end_id} 기반 URL 생성 중...")
            try:
                start = int(start_id)
                end = int(end_id)
                for product_id in range(start, end + 1):
                    product_url = f"{self.base_url}/shop/view.php?index_no={product_id}"
                    product_urls.append(product_url)
            except ValueError:
                logger.error("ID 범위는 숫자여야 합니다.")
        
        # 3. 모든 카테고리 스캔
        elif scan_all_categories:
            logger.info("모든 카테고리 스캔 중...")
            try:
                # 대신 ID 범위로 URL 생성 (예시 ID 범위: 1-200000)
                start_id = 1
                end_id = 200000  # 적절한 최대 ID 범위 설정
                logger.info(f"ID 범위 {start_id}-{end_id}로 URL 생성")
                
                for product_id in range(start_id, end_id + 1):
                    product_url = f"{self.base_url}/shop/view.php?index_no={product_id}"
                    product_urls.append(product_url)
                
            except Exception as e:
                logger.error(f"URL 생성 중 오류: {str(e)}")
        
        logger.info(f"총 {len(product_urls)}개 상품 URL 생성 완료")
        return product_urls
    
    def crawl_products(self, product_urls):
        """
        여러 상품 URL을 크롤링하여 데이터 수집
        
        Args:
            product_urls: 크롤링할 상품 URL 목록
            
        Returns:
            수집된 웹 데이터 (URL을 키로 하는 딕셔너리)
        """
        web_data = {}
        
        # 병렬 처리를 위한 스레드 풀 생성 - 최대 작업자 수 제한
        max_workers = min(self.max_workers, 5)  # 최대 5개 스레드로 제한
        logger.info(f"병렬 크롤링 시작: {len(product_urls)}개 URL, {max_workers}개 스레드 사용")
        
        # 진행 상황 추적 변수
        total_urls = len(product_urls)
        processed_urls = 0
        successful_urls = 0
        failed_urls = 0
        skipped_urls = 0  # 존재하지 않는 상품
        
        print(f"\n{'='*50}")
        print(f"🔍 상품 크롤링 시작: 총 {total_urls}개 URL")
        print(f"{'='*50}")
        
        # 진행 상황 표시를 위한 tqdm 설정
        progress_bar = tqdm(total=total_urls, desc="상품 크롤링", unit="페이지")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # URL별로 작업 제출
            future_to_url = {executor.submit(self.crawl_product, url): url for url in product_urls}
            
            # 진행 상황 표시
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                processed_urls += 1
                
                try:
                    data = future.result()
                    if data:
                        web_data[url] = data
                        successful_urls += 1
                        progress_bar.set_description(f"✅ 성공: {successful_urls}/{processed_urls}")
                    else:
                        # 상품이 존재하지 않는 경우
                        skipped_urls += 1
                        progress_bar.set_description(f"⏩ 건너뜀: {skipped_urls}/{processed_urls}")
                    
                    # 메모리 관리
                    if processed_urls % 10 == 0:
                        self.memory_manager.check_memory()
                        
                except Exception as e:
                    failed_urls += 1
                    logger.error(f"URL 처리 중 오류 발생: {url} - {str(e)}")
                    progress_bar.set_description(f"❌ 실패: {failed_urls}/{processed_urls}")
                
                # 진행 상황 업데이트
                progress_bar.update(1)
                
                # 상세 상태 정보 업데이트 (5% 단위로)
                if processed_urls % max(1, total_urls // 20) == 0 or processed_urls == total_urls:
                    progress_percent = (processed_urls / total_urls) * 100
                    progress_bar.set_postfix({
                        "진행률": f"{progress_percent:.1f}%", 
                        "성공": successful_urls,
                        "실패": failed_urls, 
                        "건너뜀": skipped_urls
                    })
                    
                    # 주기적으로 상세 정보 출력
                    if processed_urls % max(1, total_urls // 5) == 0:
                        print(f"\n📊 진행 상황 (처리: {processed_urls}/{total_urls}):")
                        print(f"  - 성공: {successful_urls}개 ({(successful_urls/processed_urls)*100:.1f}%)")
                        print(f"  - 실패: {failed_urls}개 ({(failed_urls/processed_urls)*100:.1f}%)")
                        print(f"  - 건너뜀: {skipped_urls}개 ({(skipped_urls/processed_urls)*100:.1f}%)")
        
        # 진행 바 닫기
        progress_bar.close()
        
        # 최종 결과 출력
        print(f"\n{'='*50}")
        print(f"📋 크롤링 완료 결과:")
        print(f"  - 총 URL: {total_urls}개")
        print(f"  - 성공: {successful_urls}개 ({(successful_urls/total_urls)*100:.1f}%)")
        print(f"  - 실패: {failed_urls}개 ({(failed_urls/total_urls)*100:.1f}%)")
        print(f"  - 없는 상품: {skipped_urls}개 ({(skipped_urls/total_urls)*100:.1f}%)")
        print(f"{'='*50}")
        
        logger.info(f"총 {len(web_data)}개 상품 페이지 크롤링 완료")
        return web_data

    def crawl_product(self, url):
        """
        단일 상품 URL 크롤링
        
        Args:
            url: 크롤링할 상품 URL
            
        Returns:
            수집된 데이터 딕셔너리
        """
        try:
            # 상품 상세 정보 가져오기
            product_info = self.get_product_details(url)
            if not product_info:
                return None
            
            # 텍스트 및 이미지 URL 추출
            text = f"{product_info['name']} {product_info['description']} {' '.join(str(spec) for spec in product_info['specs'].values())}"
            images = product_info['images']
            
            return {
                'text': text,
                'images': images,
                'product_info': product_info
            }
            
        except Exception as e:
            logger.error(f"상품 크롤링 중 오류: {url} - {str(e)}")
            return None

    def export_found_product_ids(self, output_path):
        """
        발견된 상품 ID를 파일로 내보내기
        
        Args:
            output_path: 저장할 파일 경로
        """
        try:
            # 디렉토리 생성
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # ID 목록 저장
            with open(output_path, 'w', encoding='utf-8') as f:
                for product_id in sorted(self.found_product_ids):
                    f.write(f"{product_id}\n")
                
            logger.info(f"{len(self.found_product_ids)}개 상품 ID를 {output_path}에 저장했습니다.")
            
        except Exception as e:
            logger.error(f"상품 ID 내보내기 실패: {str(e)}") 