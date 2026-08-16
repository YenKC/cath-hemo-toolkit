#!/usr/bin/env python3
"""
Generate the synthetic case log that pairs with the synthetic recording.

    python scripts/make_sample_log.py

Writes sample/SYNTH01.docx: a Mac-Lab-style case log in the same shape a real one has, so
the viewer's log panel and event timeline can be tried without any patient data. Nothing
here describes a real procedure.

The layout the parser relies on is a line holding only a time, followed by the event text,
followed by any comment lines, repeated. Everything before the first timestamp is the
patient-information block. Times fall inside SYNTH01's 9:00:00 - 9:02:30 span so every
event lands on the recording, and the set covers each category the viewer colours
separately: procedure, vitals, pressure, med, lab, inflation and device.
"""
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / 'sample'

HEAD = [
    'Patient Information',
    'Patient Name SYNTHETIC, Sample',
    'Study Date 1/1/2026',
    'MRN SYNTH01',
    'Date of Birth 1/1/1960',
    'Age 66 Years',
    'Gender Male',
    'Time', 'Summary', 'Comment', 'Phase:',
]

# (time, summary, comment or None)
EVENTS = [
    ('9:00:00 AM', 'Procedure: Sign in', None),
    ('9:00:04 AM', 'SpO2 98%; HR 68 bpm; 132/74/94 NBP; RR 14/min', None),
    ('9:00:11 AM', 'Procedure: Time out', None),
    ('9:00:16 AM', 'Procedure: Right radial artery was punctured.', None),
    ('9:00:22 AM', 'Procedure: LCA Angio-Left coronary artery cannulation.', None),
    ('9:00:27 AM', 'AO : 128/72/91, HR = 68, II', None),
    ('9:00:27 AM', 'Snapshot: AO : 128/72/91', None),
    ('9:00:34 AM', 'Heparin 5000u/ml IC 3,000 units', None),
    ('9:00:41 AM', 'Procedure: Check ACT', '240"'),
    ('9:00:52 AM', 'Balloon inflated for 12 sec @ 8 atm in the pLAD.', None),
    ('9:01:05 AM', 'SpO2 97%; HR 74 bpm; 121/70/87 NBP; RR 15/min', None),
    ('9:01:14 AM', 'Balloon inflated for 18 sec @ 10 atm in the pLAD.', None),
    ('9:01:30 AM', 'Thrombectomy: 0 cc out on the pLAD.', None),
    ('9:01:38 AM', 'Stent deployed for 14 sec @ 14 atm in the pLAD.', None),
    ('9:01:52 AM', 'Balloon inflated for 10 sec @ 16 atm in the pLAD.', 'post-dilatation'),
    ('9:02:02 AM', 'NTG 5mg/10ml IC 200 mcg', None),
    ('9:02:08 AM', 'PCW : 14/9/11, HR = 80, II', None),
    ('9:02:14 AM', 'SpO2 98%; HR 80 bpm; 126/71/89 NBP; RR 15/min', None),
    ('9:02:18 AM', 'SAT: AO 98.0%', None),
    ('9:02:23 AM', 'Procedure: Contrast Amount', '95 ml'),
    ('9:02:28 AM', 'Procedure: Patient leaves the room', None),
]

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>'
)


def para(text):
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def build_document():
    body = [para(h) for h in HEAD]
    for when, summary, comment in EVENTS:
        body.append(para(when))
        body.append(para(summary))
        if comment:
            body.append(para(comment))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + ''.join(body) + '</w:body></w:document>'
    )


def main():
    OUT.mkdir(exist_ok=True)
    path = OUT / 'SYNTH01.docx'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', RELS)
        z.writestr('word/document.xml', build_document())
    kinds = sum(1 for _, s, _ in EVENTS if 'inflated' in s or 'deployed' in s)
    print(f'wrote {path}  ({path.stat().st_size:,} bytes)')
    print(f'  {len(EVENTS)} events, {kinds} balloon/stent inflations')
    print(f'  spans {EVENTS[0][0]} to {EVENTS[-1][0]}, inside SYNTH01\'s 9:00:00-9:02:30')


if __name__ == '__main__':
    main()
