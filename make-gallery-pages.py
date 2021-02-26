#!/usr/bin/env python

import os
import yaml
import uuid
import shutil
import base64
import jinja2
import requests
import argparse
from lxml import etree


# global vars
source_dir = "./source"
gallery_dir = f"./source/gallery"
template_dir = f"./source/_templates"
static_dir = f"./source/_static"


def render_page(template, data, outpath="./index.rst"):
    Loader = jinja2.FileSystemLoader(searchpath="./")
    env = jinja2.Environment(loader=Loader)
    template = env.get_template(template)

    text = template.render(data)
    with open(outpath, "w") as f:
        f.write(text)


def get_metadata_from_hs(hsguid):
    """
    This function collects metadata from a hydroshare resource
    """
    data = {}
    try:
        r = requests.get(f"https://hydroshare.org/hsapi/resource/{hsguid}/scimeta")
        if r.status_code != 200:
            raise Exception

        # encode response as bytestring
        txt = r.text.encode()

        # parse into lxml object
        root = etree.fromstring(txt)

        creators = root.findall(".//dc:creator", root.nsmap)
        data["authors"] = []

        for creator in creators:
            terms = creator.find("rdf:Description", root.nsmap)
            d = {}
            for att in ["name", "organization", "email"]:
                val = terms.find(f"hsterms:{att}", root.nsmap)
                if val is not None:
                    d[att] = val.text

            # save the user's profile page if it exists
            user_url = terms.find(f'hsterms:description',root.nsmap)
            if user_url is not None:
                d['url'] = f'https://hydroshare.org{user_url.text}'

            data["authors"].append(d)

        # get the resource title and description
        data["title"] = root.find(".//dc:title", root.nsmap).text

        # todo: the encoding of description does not preserve newlines.
        data["description"] = (
            root.find(".//dcterms:abstract", root.nsmap)
            .text.encode("ascii", "ignore")
            .decode()
        )

        # get the keywords
        subject_kw = root.findall("rdf:Description/dc:subject", root.nsmap)
        keywords = [kw.text for kw in subject_kw]
        if len(keywords) > 0:
            data["keywords"] = keywords

    except Exception:
        print(f"Failed to get hydroshare data for resource id: {hsguid}")
        return None

    return data


def copy_static(data):
    """
    copy static files to _static directory
    """

    if 'thumbnail' in data.keys():
        # move thumbnail to _static and rename it
        thumbnail_path = os.path.abspath(
            os.path.join(subdir, data["thumbnail"])
        )
        if os.path.exists(thumbnail_path):
            thumbnail_new_name = f'thumbnail-{data["label"]}'
            shutil.copyfile(thumbnail_path, f"{static_dir}/{thumbnail_new_name}")
            data["thumbnail"] = thumbnail_new_name
            return data

    # set thumbnail using the default "unknown" image
    print('WARNING: Missing thumbnail, setting to default image')
    data['thumbnail'] = 'missing-thumbnail.png'

    return data


def write_yaml_cache(outdir, data, filename='.cache.yaml'):
    """
    saves data to yaml file
    outdir: directory to save file
    filename: name of file, default .cache.yaml
    data: dictionary of data to save
    """

    with open(os.path.join(outdir, filename), 'w') as f:
        yaml.dump(data, f)


def build_example_page(conf):
    """
    creates example landing page from a conf.yaml file
    conf: full path to conf.yaml file
    returns: dictionary of data for the example or None
    """
    with open(conf, "r") as f:
        # load yaml data
        yaml_data = yaml.load(f, Loader=yaml.FullLoader)

        hsdata = None
        hsid = yaml_data.get("hydroshare", {}).get("id")
        # collect hydroshare data if a resource id is provided
        # in the yaml file
        if hsid is not None:
            # load data from hydroshare
            hsdata = get_metadata_from_hs(hsid)
            if hsdata is None:
                print('something happened when collecting hs metadata')

                # exit early
                return None

        # combine hsdata and yaml data.
        # note, yaml data will overwite hs data
        data = hsdata or {}
        data.update(yaml_data)

        # make sure a page label exists in data. If not, create one.
        if "label" not in data.keys():
            try:
                # set the label as the HS id if it exists
                data['label'] = data['hydroshare']['id']
            except Exception:
                # set to a base64 encoding of the title
                data['label'] = base64.b64encode(data['title'].encode()).decode()

        # clean newlines from description
        data['description'] = data['description'].replace('\n', '')
        data['description'] = data['description'].replace('\r', '<br>')

        # save the configuration data to a .cache.yaml file
        # so the site can be re-build without querying metadata
        # from HydroShare every time.
        write_yaml_cache(subdir, data, filename='.cache.yaml')

        # write the rST page for this example
        render_page(
            os.path.join(template_dir, "landingpage.rst"),
            data,
            outpath=os.path.join(subdir, "index.rst"),
        )

        return data


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "-g",
        "--gallery",
        default=gallery_dir,
        help=f"path of the gallery to build, if nothing is provided all galleries in {gallery_dir} will be built.",
    )

    args = p.parse_args()
    subgalleries = {}

    # loop through each directory in the gallery
    # only process directories that contain conf.yaml files,
    # ignore all other directories
    for subdir, dirs, files in os.walk(args.gallery):
        if "conf.yaml" in files:
            print(f"processing: {subdir}")

            # build the example landing rST page
            conf = os.path.join(subdir, "conf.yaml")
            data = build_example_page(conf)

            # save the sub-gallery and category if the example was
            # build successfully
            if data is not None:

                # move static data
                data = copy_static(data)

                # save this metadata for the sub-gallery page too
                subgallery_path = os.path.dirname(os.path.dirname(subdir))
                category = os.path.basename(os.path.dirname(subdir))

                # add the sub-gallery to a dictionary if it doesn't already
                # exist. This dictionary will be used to build the sub-gallery
                # pages. Do the same for the categories which will be rendered
                # on the gallery homepage.
                if subgallery_path not in subgalleries.keys():
                    subgalleries[subgallery_path] = {}
                if category not in subgalleries[subgallery_path].keys():
                    subgalleries[subgallery_path][category] = []
                subgalleries[subgallery_path][category].append(data)

#            conf = os.path.join(subdir, "conf.yaml")
#            print(f"processing: {subdir}")
#            with open(conf, "r") as f:
#                # load yaml data
#                yaml_data = yaml.load(f, Loader=yaml.FullLoader)
#
#                hsdata = None
#                hsid = yaml_data.get("hydroshare", {}).get("id")
#                # collect hydroshare data if a resource id is provided
#                # in the yaml file
#                if hsid is not None:
#                    # load data from hydroshare
#                    hsdata = get_metadata_from_hs(hsid)
#                    if hsdata is None:
#                        # something happened when collecting hs metadata
#                        continue
#
#                # combine hsdata and yaml data.
#                # note, yaml data will overwite hs data
#                data = hsdata or {}
#                data.update(yaml_data)
#
#                # make sure a page label exists in data. If not, create one.
#                if "label" not in data.keys():
#                    try:
#                        # set the label as the HS id if it exists
#                        data['label'] = data['hydroshare']['id']
#                    except Exception:
#                        # set to a base64 encoding of the title
#                        data['label'] = base64.b64encode(data['title'].encode()).decode()
#
#                # clean newlines from description
#                data['description'] = data['description'].replace('\n', '')
#                data['description'] = data['description'].replace('\r', '<br>')
#
#                # save the configuration data to a .cache.yaml file
#                # so the site can be re-build without querying metadata
#                # from HydroShare every time.
#                write_yaml_cache(subdir, data, filename='.cache.yaml')
#
#                # write the rST page for this example
#                render_page(
#                    os.path.join(template_dir, "landingpage.rst"),
#                    data,
#                    outpath=os.path.join(subdir, "index.rst"),
#                )


    # build the sub-gallery pages
    with open(os.path.join(source_dir, "conf.yaml"), "r") as f:
        yaml_data = yaml.load(f, Loader=yaml.FullLoader)

        # build the sub-gallery pages
        gallery_labels = {}
        for sub, sub_data in subgalleries.items():
            # create a label for the subgallery page
            # set to a base64 encoding of the title
            subname = os.path.basename(sub)
            id = base64.b64encode(subname.encode()).decode()
            gallery_labels[sub] = id

            # generate page title. This is necessary for the TOC
            # get the title from the top-level conf if it exists,
            # otherwise get it from the directory name
            title = None
            for v in yaml_data["galleries"]:
                if sub == v['gallery_path']:
                    title = v['display_name']
                    break
            if title is None:
                title = f"{os.path.basename(sub)} Gallery"

            render_page(
                os.path.join(template_dir, "gallery.rst"),
                {"label": id, "gallery_title": title, "categories": sub_data},
                outpath=os.path.join(sub, "index.rst"),
            )

        # build the homepage

        # add panels for sub-galleries
        homepage_panels = []
        for v in yaml_data["galleries"]:
            if v["gallery_path"] in gallery_labels:
                v["label"] = gallery_labels[v["gallery_path"]]

#                # overwrite display_name if it's provided in the conf
#                if 'display_name' in v.keys():


                # only render galleries on the homepage that have labels. 
                # this will ignore any galleries defined in conf.yaml that
                # do not have rendered example pages.
                homepage_panels.append(v)

        render_page(
            os.path.join(template_dir, "homepage.rst"),
            {'galleries': homepage_panels},
            outpath=os.path.join(source_dir, "index.rst"),
        )
