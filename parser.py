import os
import json
from bs4 import BeautifulSoup

def find_html_files(start_path):
    """Find all HTML files in a directory, prioritizing index.html."""
    html_files = []
    for root, _, files in os.walk(start_path):
        for file in files:
            if file.lower().endswith('.html'):
                if file.lower() == 'index.html' and root == start_path:
                    html_files.insert(0, os.path.join(root, file))
                else:
                    html_files.append(os.path.join(root, file))
    return html_files

def get_page_slug(filepath, soup):
    """Determine the page slug from the file or a meta tag."""
    og_url_tag = soup.find('meta', property='og:url')
    if og_url_tag and og_url_tag.get('content'):
        url_path = og_url_tag['content'].strip().split('/')[-1]
        slug = url_path.replace('.html', '')
        return '/' if slug == 'index' else f"/{slug.lstrip('/')}"
        
    slug = os.path.basename(filepath).replace('.html', '')
    return '/' if slug == 'index' else f"/{slug}"

def extract_menu_structure(soup):
    """
    Finds and parses the menu structure from a soup object, specifically targeting
    Tilda's mega menu where submenus are distinct lists linked by title.
    """
    menu_container = soup.find('div', {'data-record-type': ['199', '983']}) or soup.find('header')
    if not menu_container:
        return [], None

    all_lists_in_menu = menu_container.find_all('ul')
    
    parsed_lists = []
    for ul in all_lists_in_menu:
        current_list = []
        for a in ul.find_all('a', href=True):
            text = a.get_text(strip=True)
            if text:
                href = a.get('href', '#').strip()
                if href.startswith('http') or href == '#':
                    slug = href
                else:
                    slug = f"/{href.replace('.html', '').lstrip('/')}"
                    if 'index' in slug:
                        slug = '/'
                current_list.append({'title': text, 'slug': slug})
        if current_list:
            parsed_lists.append(current_list)

    if not parsed_lists:
        return [], menu_container.get('id')

    # Heuristic to find the main menu:
    first_item_titles = {lst[0]['title'] for lst in parsed_lists if len(lst) > 1}
    main_menu_candidate = None
    max_score = -1

    if not first_item_titles: # Handle cases with no submenus
        main_menu_candidate = max(parsed_lists, key=len) if parsed_lists else []
    else:
        for lst in parsed_lists:
            # A list with just one item is unlikely to be the main nav bar in a mega menu.
            if len(lst) <= 1: continue
            
            matches = 0
            list_titles = {item['title'] for item in lst}
            for title in list_titles:
                if any(fi.startswith(title) for fi in first_item_titles):
                    matches += 1
            
            # Score prioritizes matches but penalizes very long lists, as the main menu is usually concise.
            score = matches - (len(lst) / 10.0)
            
            if score > max_score:
                max_score = score
                main_menu_candidate = lst
    
    if not main_menu_candidate:
         # Fallback for simple menus
         main_menu_candidate = min(parsed_lists, key=len) if parsed_lists else []
         if not main_menu_candidate:
            return [], menu_container.get('id')
    
    submenu_map = {lst[0]['title']: lst[1:] for lst in parsed_lists if lst and lst != main_menu_candidate and len(lst) > 1}

    # Build the final hierarchical menu
    final_menu = []
    for item in main_menu_candidate:
        menu_item = item.copy()
        
        # Find a matching submenu using flexible startswith logic
        found_submenu = None
        for key, submenu in submenu_map.items():
            if key.startswith(item['title']):
                found_submenu = submenu
                break
        
        if found_submenu:
            menu_item['submenu'] = found_submenu
            if menu_item.get('slug') == '#':
                menu_item.pop('slug', None)
        
        final_menu.append(menu_item)
    
    return final_menu, menu_container.get('id')

def parse_page_content(soup):
    """Extract structured content from a BeautifulSoup object."""
    content = []
    main_content = soup.find('div', id='allrecords') or soup.body
    
    if not main_content:
        return []

    for element in main_content.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'img'], recursive=True):
        if element.find_parent('nav') or element.find_parent('header'):
            continue # Skip elements inside navigation or headers already parsed

        if element.name in ['h1', 'h2', 'h3']:
            text = element.get_text(strip=True)
            if text:
                content.append({"type": "heading", "text": text})
        elif element.name == 'p':
            text = element.get_text(strip=True)
            if text:
                content.append({"type": "paragraph", "text": text})
        elif element.name in ['ul', 'ol']:
            items = [li.get_text(strip=True) for li in element.find_all('li') if li.get_text(strip=True)]
            if items:
                content.append({"type": "list", "items": items})
        elif element.name == 'img':
            src = element.get('src')
            if src and not src.startswith('data:'):
                content.append({"type": "image", "src": src})
    
    return content

def parse_tilda_export(project_path):
    """Main function to parse the extracted Tilda project."""
    extracted_dir = os.path.join(project_path, 'extracted')
    if not os.path.isdir(extracted_dir):
        return {"error": "Extracted directory not found."}
    
    html_files = find_html_files(extracted_dir)
    if not html_files:
        return {"error": "No HTML files found in the export."}

    structured_data = {"pages": [], "menu": []}
    menu_container_id = None

    # Step 1: Parse the main page (index.html) to define the menu structure.
    if html_files:
        with open(html_files[0], 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'lxml')
            structured_data['menu'], menu_container_id = extract_menu_structure(soup)

    # Step 2: Parse all pages for content, excluding the menu container.
    for file_path in html_files:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'lxml')
            
            # If a menu container was found, remove it from the soup to prevent re-parsing.
            if menu_container_id:
                menu_to_remove = soup.find('div', id=menu_container_id)
                if menu_to_remove:
                    menu_to_remove.extract()
            
            page_title = soup.title.string.strip() if soup.title else "Untitled"
            page_slug = get_page_slug(file_path, soup)
            page_content = parse_page_content(soup)
            
            if page_content:
                structured_data["pages"].append({
                    "title": page_title,
                    "slug": page_slug,
                    "content": page_content
                })

    return structured_data

def save_parsed_data(project_path, data):
    """Saves the structured data to a JSON file in the project directory."""
    filepath = os.path.join(project_path, 'parsed_data.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4) 