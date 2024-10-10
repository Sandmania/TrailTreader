import xml.etree.ElementTree as ET
import argparse

def remove_namespace(root, namespace):
    # Remove namespace prefix from element names
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]

def reverse_gpx_route(gpx_file):
    # Parse the GPX file
    tree = ET.parse(gpx_file)
    root = tree.getroot()

    # Define the namespace
    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}

    # Find all rtept elements under the rte element
    rte = root.find('.//gpx:rte', namespaces=ns)
    if rte is not None:
        rtepts = rte.findall('gpx:rtept', namespaces=ns)

        # Reverse the list of rtept elements
        rtepts.reverse()

        # Replace the existing rtept elements with the reversed list
        rte[:] = rtepts

        # Remove namespace prefix before writing to file
        remove_namespace(root, ns)

        # Write the modified XML back to the input file
        tree.write(gpx_file, xml_declaration=True, encoding='utf-8', method='xml')

        print(f"Successfully reversed and saved the GPX file to {gpx_file}")
    else:
        print("No rte element found in the GPX file.")

if __name__ == "__main__":
    # Setup argument parser
    parser = argparse.ArgumentParser(description='Reverse the route points in a GPX file.')
    parser.add_argument('filename', metavar='FILENAME', help='Path to the GPX file')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Call function to reverse GPX route
    reverse_gpx_route(args.filename)
