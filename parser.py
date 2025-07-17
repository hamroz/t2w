import os
import json
from bs4 import BeautifulSoup

def find_html_files(start_path):
    """Find all HTML files in a directory, prioritizing index.html."""
    html_files = []
    for root, _, files in os.walk(start_path):
        for file in files:
            if file.lower().endswith('.html'):
                # Give priority to the root index.html
                if file.lower() == 'index.html' and root == start_path:
                    html_files.insert(0, os.path.join(root, file))
                else:
                    html_files.append(os.path.join(root, file))
    return html_files

def get_page_slug(filepath, soup):
    """Determine the page slug from the file or a meta tag."""
    # Try to get slug from <meta property="og:url">
    og_url_tag = soup.find('meta', property='og:url')
    if og_url_tag and og_url_tag.get('content'):
        # Extract path from full URL
        return "/" + og_url_tag['content'].strip().split('/')[-1].replace('.html', '')

    # Fallback to filename
    slug = os.path.basename(filepath).replace('.html', '')
    if slug == 'index':
        return '/'
    return f"/{slug}"

def parse_menu(soup, html_files):
    """Extract menu structure from <nav> or <header>."""
    menu = []
    nav_tags = soup.find_all(['nav', 'header'])
    
    for tag in nav_tags:
        for a in tag.find_all('a', href=True):
            href = a['href']
            title = a.get_text(strip=True)
            
            # Ensure it's a link to a known page and has a title
            if href.endswith('.html') and title:
                # Find the full path of the linked file
                base_name = os.path.basename(href)
                # This is a simplification; a real scenario might need to resolve paths better
                if any(f.endswith(base_name) for f in html_files):
                    slug = f"/{base_name.replace('.html', '')}"
                    if base_name == 'index.html':
                        slug = '/'
                    
                    if not any(item['slug'] == slug for item in menu):
                         menu.append({"title": title, "slug": slug})
    return menu

def parse_page_content(soup):
    """Extract structured content from a BeautifulSoup object."""
    content = []
    # This is a simplified selector. Tilda's structure is complex.
    # We are looking for a main content area to avoid parsing headers/footers repeatedly.
    main_content = soup.find('div', id='allrecords') or soup.body
    
    if not main_content:
        return []

    # Find all relevant tags, in order of appearance.
    for element in main_content.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'img'], recursive=True):
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
            # Exclude placeholder images or inline data
            if src and not src.startswith('data:'):
                content.append({"type": "image", "src": src})
    
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
    
    # First, parse the main page (index.html) to find the menu
    if html_files:
        with open(html_files[0], 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'lxml')
            structured_data['menu'] = parse_menu(soup, html_files)

    # Then, parse all pages for content
    for file_path in html_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'lxml')
            
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