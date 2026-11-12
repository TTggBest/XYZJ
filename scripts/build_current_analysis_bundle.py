"""Build an unpublished V21 candidate with the current-analysis bridge wiring."""
import argparse
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(source):
    with ZipFile(BytesIO(source)) as archive:
        files = {i.filename:archive.read(i) for i in archive.infolist() if not i.is_dir()}
    name = 'zhiju/bridge.py'
    old = "'channel_theme_contract': batch.channel_theme_contract(item, plot),"
    new = "'channel_theme_contract': channel.get('current_channel_theme_contract') or batch.channel_theme_contract(item, plot),"
    text = files[name].decode()
    if old not in text: raise ValueError('V21 bridge source differs; review its current-analysis entry before building')
    files[name] = text.replace(old,new,1).encode()
    name = 'xy-pack-v21/scripts/prompt_inputs.py'
    text = files[name].decode()
    start = text.index('def focused_title_prompt(')
    at = text.index('    cast = visual_cast_contract(context)',start)
    text = text[:at] + """    if theme.get('source') == 'current_applied_analysis':
        acceptance.pop('accepted_theme_signals', None)
        acceptance['per_direction_requirement'] = 'Use applicable current guidance and real plot facts. No literal theme keyword quota.'
""" + text[at:]
    files[name] = text.encode()
    manifest = json.loads(files['zhiju-workflow.json'])
    manifest['executor_protocol'] = max(17,int(manifest.get('executor_protocol',1)))
    files['zhiju-workflow.json'] = json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    output = BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,content in files.items(): archive.writestr(name,content)
    return output.getvalue()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(build(args.source.read_bytes()))
