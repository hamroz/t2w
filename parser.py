import os
import json
from bs4 import BeautifulSoup

def find_html_files(start_path):
    """
    Find all 'main' HTML files in a directory, ignoring partials found in subdirectories.
    It prioritizes index.html at the root.
    """
    html_files = []
    # We walk the directory but explicitly tell walk not to descend into 'files' dirs,
    # which is where Tilda stores partial body HTMLs.
    for root, dirs, files in os.walk(start_path):
        if 'files' in dirs:
            dirs.remove('files')

        for file in files:
            if file.lower().endswith('.html'):
                full_path = os.path.join(root, file)
                # Give priority to the root index.html
                if file.lower() == 'index.html' and root == start_path:
                    html_files.insert(0, full_path)
                else:
                    html_files.append(full_path)
    return html_files

def get_combined_soup(main_file_path):
    """
    Loads the main HTML file and combines it with its corresponding 'body' file if it exists.
    Tilda often splits the head/header and the body content into separate files.
    """
    with open(main_file_path, 'r', encoding='utf-8') as f:
        main_soup = BeautifulSoup(f.read(), 'lxml')

    # Construct the potential path for the body file
    # e.g., page123.html -> files/page123body.html
    dir_name = os.path.dirname(main_file_path)
    file_name = os.path.basename(main_file_path)
    body_file_name = file_name.replace('.html', 'body.html')
    body_file_path = os.path.join(dir_name, 'files', body_file_name)

    if os.path.exists(body_file_path):
        with open(body_file_path, 'r', encoding='utf-8') as f:
            body_soup = BeautifulSoup(f.read(), 'lxml')

        # The main content of the page is usually within a div with id="allrecords"
        main_content_container = main_soup.find('div', id='allrecords')
        body_content = body_soup.find('div', id='allrecords')

        if main_content_container and body_content:
            # Replace the container's content with the content from the body file
            main_content_container.clear()
            for child in body_content.find_all(recursive=False):
                main_content_container.append(child)

    return main_soup


def get_page_slug(filepath, soup):
    """Determine the page slug from the file or a meta tag."""
    # Try to get slug from <meta property="og:url">
    og_url_tag = soup.find('meta', property='og:url')
    if og_url_tag and og_url_tag.get('content'):
        # Extract path from full URL
        return "/" + og_url_tag['content'].strip().split('/')[-1].replace('.html', '')

    # Fallback to filename
    slug = os.path.basename(filepath).replace('.html', '')
    if slug.lower() == 'index':
        return '/'
    return f"/{slug}"

def parse_menu(soup):
    """
    Extracts the main menu and submenus from the Tilda page soup.
    Tilda uses a specific structure where main menu items link to submenu "hooks".
    """
    menu = []
    
    # Find the main navigation container
    main_nav = soup.find('nav', class_='t228__centercontainer')
    if not main_nav:
        return []

    # Find all top-level menu items
    main_menu_links = main_nav.select('.t228__list_item > a.t-menu__link-item')

    for link in main_menu_links:
        title = link.get_text(strip=True)
        href = link.get('href', '')
        
        menu_item = {"title": title}

        # Case 1: Item has a submenu
        if href.startswith('#submenu:'):
            submenu_container = soup.find('div', {'data-tooltip-hook': href})
            if submenu_container:
                submenu_list = []
                submenu_links = submenu_container.select('.t794__list_item a')
                for sub_link in submenu_links:
                    sub_title = sub_link.get_text(strip=True)
                    sub_href = sub_link.get('href', '')
                    # Ensure slug has a leading slash
                    sub_slug = sub_href if sub_href.startswith('/') else f"/{sub_href}"
                    submenu_list.append({"title": sub_title, "slug": sub_slug})
                
                if submenu_list:
                    # The parent's slug is derived from its first child
                    menu_item['slug'] = submenu_list[0]['slug']
                    menu_item['submenu'] = submenu_list
            else:
                # A dropdown menu without content
                menu_item['slug'] = '#'
                
        # Case 2: Item is a direct link
        else:
            if href.startswith('/'):
                menu_item['slug'] = href
            elif href.endswith('.html'):
                slug = href.replace('.html', '')
                menu_item['slug'] = '/' if slug == 'index' else f'/{slug}'
            else:
                # Keep non-standard links as they are (e.g., tel:, mailto:)
                menu_item['slug'] = href
        
        menu.append(menu_item)

    return menu

def parse_page_content(soup):
    """Extract structured content from a BeautifulSoup object, focusing on Tilda-specific elements while maintaining document order."""
    content = []
    
    # Find the main content container, which in Tilda is usually #allrecords
    main_content = soup.find('div', id='allrecords')
    
    if not main_content:
        # Fallback to body if #allrecords is not found
        main_content = soup.body
        if not main_content:
            return []

    # To avoid parsing navigation as content, we decompose (remove) the header and footer.
    header = main_content.find('header', id='t-header')
    if header:
        header.decompose()
        
    footer = main_content.find('footer', id='t-footer')
    if footer:
        footer.decompose()

    # Remove navigation and menu elements
    for nav in main_content.find_all(['nav', 'div'], class_=lambda x: x and any(menu_class in x for menu_class in ['t228', 't794', 't-menu'])):
        nav.decompose()

    # Track processed content to avoid duplicates
    processed_texts = set()
    processed_elements = set()

    # Collect all potential content elements with their position information
    content_candidates = []

    # Get all elements that could contain content, preserving document order
    all_elements = main_content.find_all(True, recursive=True)
    
    for element in all_elements:
        # Skip if we've already processed this element or if it's in navigation
        if (id(element) in processed_elements or
            element.find_parent(['nav', 'header', 'footer']) or
            any(nav_class in element.get('class', []) for nav_class in ['t228', 't794', 't-menu'])):
            continue

        element_info = None
        element_classes = element.get('class', [])
        
        # PRIORITY 1: tn-atom elements (Tilda's main text containers)
        if 'tn-atom' in element_classes:
            # Skip empty atoms or those containing only images
            if element.find('img') and not element.get_text(strip=True):
                continue
                
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                # Check if this looks like a heading
                is_heading = (len(text_content) < 150 and 
                            (text_content.isupper() or 
                             text_content.istitle() or 
                             element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) or
                             'font-weight:700' in element.get('style', '') or
                             'font-weight:600' in element.get('style', '')))
                
                element_info = {
                    "type": "heading" if is_heading else "paragraph",
                    "text": text_content,
                    "priority": 1
                }

        # PRIORITY 2: FAQ titles (spans with specific classes)
        elif (element.name == 'span' and 
              any(title_class in element_classes for title_class in 
                  ['t585__title', 't567__title', 't221__title', 't205__title', 't-name', 't-title', '__title', '__name'])):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                element_info = {
                    "type": "heading",
                    "text": text_content,
                    "priority": 2
                }

        # PRIORITY 3: FAQ content and other structured content
        elif (element.name in ['div', 'span', 'p'] and
              any(content_class in element_classes for content_class in 
                  ['t585__content', 't585__text', 't567__content', 't567__text',
                   't221__content', 't221__text', 't205__content', 't205__text',
                   't-descr', '__content', '__text'])):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                element_info = {
                    "type": "paragraph",
                    "text": text_content,
                    "priority": 3
                }

        # PRIORITY 4: t396 elements with text content
        elif (any('t396__elem' in cls for cls in element_classes) and 
              element.get('data-elem-type') == 'text' and
              not element.find('div', class_='tn-atom')):  # Don't double-process tn-atom parents
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                is_heading = (len(text_content) < 150 and 
                            (text_content.isupper() or text_content.istitle()))
                element_info = {
                    "type": "heading" if is_heading else "paragraph",
                    "text": text_content,
                    "priority": 4
                }

        # PRIORITY 5: Traditional Tilda block content
        elif (element.name in ['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and
              any(text_class in element_classes for text_class in ['t-text', 't-title', 't-descr', 't-name'])):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                is_heading = (element.name.startswith('h') or 
                            't-title' in element_classes or
                            't-name' in element_classes)
                element_info = {
                    "type": "heading" if is_heading else "paragraph",
                    "text": text_content,
                    "priority": 5
                }

        # PRIORITY 6: Standard HTML headings and paragraphs
        elif (element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'] and
              not element.find_parent('div', class_='tn-atom') and
              not element.find_parent('div', class_=lambda x: x and 't396__elem' in x)):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                element_info = {
                    "type": "heading" if element.name.startswith('h') else "paragraph",
                    "text": text_content,
                    "priority": 6
                }

        # PRIORITY 7: Buttons and important links
        elif (element.name in ['a', 'button'] and
              any(btn_class in element_classes for btn_class in ['t-btn', 'tn-atom']) and
              not element.find_parent(['nav', 'header', 'footer'])):
            button_text = element.get_text(strip=True)
            if (button_text and len(button_text) > 2 and len(button_text) < 50 and 
                button_text not in processed_texts and
                not button_text.lower() in ['call us', 'contact', 'menu', 'home']):
                element_info = {
                    "type": "button",
                    "text": button_text,
                    "href": element.get('href', ''),
                    "priority": 7
                }

        # PRIORITY 8: Images
        elif element.name == 'img':
            src = element.get('src') or element.get('data-original')
            alt = element.get('alt', '')
            if src and not src.startswith('data:'):  # Exclude base64 embedded images
                element_info = {
                    "type": "image",
                    "src": src,
                    "alt": alt,
                    "priority": 8
                }

        # PRIORITY 9: Lists
        elif (element.name in ['ul', 'ol'] and
              not element.find_parent('div', class_=lambda x: x and any(nav_class in x for nav_class in ['t228', 't794', 't-menu']))):
            items = []
            for li in element.find_all('li'):
                li_text = li.get_text(strip=True)
                if li_text and li_text not in processed_texts:
                    items.append(li_text)
            
            if items and len(items) > 1:  # Only include lists with multiple items
                element_info = {
                    "type": "list",
                    "items": items,
                    "priority": 9
                }
                # Mark all list item texts as processed
                for item in items:
                    processed_texts.add(item)

        # If we found content, add it to candidates with position info
        if element_info:
            # Calculate the element's position in the document for sorting
            position = 0
            current = element
            while current.previous_sibling:
                current = current.previous_sibling
                position += 1
            
            # Add parent positions for more accurate sorting
            parent_positions = []
            parent = element.parent
            while parent and parent != main_content:
                parent_position = 0
                current = parent
                while current.previous_sibling:
                    current = current.previous_sibling
                    parent_position += 1
                parent_positions.append(parent_position)
                parent = parent.parent
            
            element_info['position'] = (tuple(reversed(parent_positions)), position)
            element_info['element'] = element
            content_candidates.append(element_info)
            
            # Mark text as processed
            if 'text' in element_info:
                processed_texts.add(element_info['text'])
            
            # Mark element as processed
            processed_elements.add(id(element))

    # Sort candidates by position to maintain document order
    content_candidates.sort(key=lambda x: x['position'])

    # Convert candidates to final content, removing position metadata
    for candidate in content_candidates:
        final_item = {k: v for k, v in candidate.items() if k not in ['position', 'element', 'priority']}
        content.append(final_item)

    return content

def parse_tilda_export(project_path):
    """
    Main function to parse the extracted Tilda project.
    Returns a dictionary with structured pages and menu data.
    """
    extracted_dir = os.path.join(project_path, 'extracted')
    if not os.path.isdir(extracted_dir):
        return {"error": "Extracted directory not found."}
    
    html_files = find_html_files(extracted_dir)
    if not html_files:
        return {"error": "No HTML files found in the export."}

    structured_data = {"pages": [], "menu": []}
    
    # First, parse the main page (index.html) to find the menu, since it's shared.
    if html_files:
        # Get the combined soup to ensure the header is properly loaded
        combined_soup_for_menu = get_combined_soup(html_files[0])
        structured_data['menu'] = parse_menu(combined_soup_for_menu)

    # Then, parse all pages for content
    for file_path in html_files:
        # Get the full, combined soup for the page
        soup = get_combined_soup(file_path)
        
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