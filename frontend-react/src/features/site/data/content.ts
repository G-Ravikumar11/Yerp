export interface PlanType { id: string; label: string; hint: string; sector: string; match?: RegExp }
export interface Place { n: string; k: 'hq' | 'br' | 'site'; p: [number, number]; note: string }

/** Copy and media lists for the company website. The text is taken from the earlier yalavarti.com pages. */
export const SITE = {
  slides: [
    { img: 'site/img/gallery/g108.jpg', t: 'HT networks up to 33 kV', l: 'Substations, switchyards, 400 kV extensions' },
    { img: 'site/img/banner1.jpg', t: 'Cyber Towers', l: 'Hyderabad · 1998' },
    { img: 'site/img/banner2.jpg', t: 'Metro Rail', l: 'Chennai · Bengaluru · Hyderabad' },
    { img: 'site/img/banner3.jpg', t: 'Amaravati Capital Region', l: 'Andhra Pradesh · 2016–22' }
  ],

  featured: [
    { t: 'Cyber Towers', meta: ['Hyderabad', '1998', 'IT'], img: 'site/img/banner1.jpg', d: 'External electrification and automation for the tower that started Hyderabad\'s IT corridor, executed under L&T.' },
    { t: 'Metro rail', meta: ['Chennai · Bengaluru · Hyderabad', '2012–15', 'Infrastructure'], img: 'site/img/banner2.jpg', d: 'Internal and external electrical works for Chennai Metro, the Bangalore Metro terminals and the Miyapur depot.' },
    { t: 'Amaravati capital region', meta: ['Andhra Pradesh', '2016–22', 'Institutional'], img: 'site/img/banner3.jpg', d: 'APCRDA buildings, AIIMS Mangalagiri and SRM University: electrical works across the new capital.' },
    { t: 'MIVAN townships', meta: ['Hyderabad · Odisha', '2008–13', 'Residential'], img: 'site/img/cat3.jpg', d: 'The first contractors to execute electrical works in MIVAN shuttering in Hyderabad and Odisha, at Serene County and the Vedanta township.' }
  ],

  // subset of client logos for the trust rail (white-background images, inverted in CSS)
  trust: ['c27.jpg', 'c46.png', 'c31.jpg', 'c18.jpg', 'c17.png', 'c28.jpg', 'c19.jpg', 'c20.jpg', 'c29.jpg', 'c37.png', 'c42.jpg', 'c44.jpg', 'c33.jpg', 'c24.jpg'],

  plan: {
    types: [
      { id: 'res', label: 'Residential', hint: 'Towers, villas, townships', sector: 'Residential' },
      { id: 'com', label: 'Commercial', hint: 'Offices, malls, multiplexes', sector: 'Commercial' },
      { id: 'inst', label: 'Institutional', hint: 'Hospitals, campuses, stadiums', sector: 'Commercial', match: /aiims|iim|iit|college|university|nmims|stadium|srm|police|study/i },
      { id: 'ind', label: 'Industrial & power', hint: 'Plants, pharma, switchyards', sector: 'Industrial' },
      { id: 'it', label: 'IT & SEZ', hint: 'Tech parks, data centres', sector: 'IT & SEZ' },
      { id: 'hos', label: 'Hospitality', hint: 'Hotels, service apartments', sector: 'Hospitality' }
    ],
    scopes: [
      { id: 'electrical', label: 'Electrical', inc: 'HT up to 33 kV, transformers, panels, cabling, lighting, earthing' },
      { id: 'fire', label: 'Fire fighting', inc: 'Pump room, hydrants, sprinklers, alarm & detection, gas suppression' },
      { id: 'phe', label: 'Plumbing (PHE)', inc: 'Water supply, drainage, STP / WTP, rainwater systems' },
      { id: 'panels', label: 'Panels', inc: 'LT, PCC, MCC and APFC panels built in our own factory' },
      { id: 'elv', label: 'ELV & BMS', inc: 'CCTV, access control, BMS cabling, PA, UPS distribution' },
      { id: 'testing', label: 'Testing', inc: 'Relay calibration, breaker & transformer tests, commissioning' }
    ],
    stages: ['Design / planning', 'Tendering', 'Under construction', 'Existing building']
  },
  services: [
    {
      id: 'electrical', title: 'Electrical', tag: 'Up to 33 kV', img: 'site/img/gallery/g106.jpg', size: 'xl', color: 'cyan',
      short: 'External and internal electrical works, from the main HT line through distribution to the last point of use.',
      intro: 'We design, install, alter and maintain electrical systems, from low to high voltage distribution down to end-use devices.',
      list: ['HT installation up to 33 kV', 'Transformers, HT & LT panels', 'Cables, cable trays, rising mains & bus ducts', 'Earthing and lightning protection', 'Plant lighting: flameproof, street and yard lighting', 'Data centres and call centres: power distribution & UPS', 'Addressable fire alarm, CCTV, access control', 'BMS control cabling', 'Commissioning of instrumentation, control and panels', 'Energy conservation and consumption monitoring consultancy', 'AMC contracts for banks, software companies and data units']
    },
    {
      id: 'fire', title: 'Fire Fighting', tag: 'Detect · Protect', img: 'site/img/gallery/g119.jpg', size: 'tall', color: 'fire',
      short: 'Complete fire detection and protection that catches a fire at its incipient stage.',
      intro: 'Complete and comprehensive systems to detect fire early, so a major outbreak can be prevented. Our 24-hour call-out team attends to emergency calls.',
      list: ['Pump rooms: hydrant, sprinkler & jockey pumps', 'Hydrant systems: wet riser and dry riser', 'Sprinkler systems', 'Addressable & conventional fire alarm, detectors, MCPs, hooters', 'Gas suppression: FM200, INERGEN, NAF S-III, CO₂, NOVEC 1230', 'Extinguishers: CO₂, DCP, foam, water', 'Integrated building management & PA systems', '24-hour emergency call-out']
    },
    {
      id: 'panels', title: 'Panels & Engineering', tag: 'Made in-house', img: 'site/img/gallery/g111.jpg', size: 'md', color: 'amber',
      short: 'LT panels and cable trays built by our sister company, Yalavarti Engineering.',
      intro: 'Yalavarti Engineering Pvt. Ltd. is an electrical panel builder and "A" grade electrical contractor in Hyderabad, led by Managing Director Mr. Y. Vamsi Krishna, who started the firm in 1998 working under L&T ECC.',
      list: ['LT distribution panels', 'PCC, MCC and APFC panels', 'Feeder pillars and kiosks', 'Cable trays and raceways', 'Factory testing before dispatch']
    },
    {
      id: 'phe', title: 'PHE Works', tag: 'Water in · water out', img: 'site/img/gallery/g112.jpg', size: 'md', color: 'cyan',
      short: 'Public health engineering: water supply, drainage and treatment plants.',
      intro: 'Plumbing and public health engineering for high-rise towers, campuses and townships.',
      list: ['Sanitary fixtures: EWCs, wash basins, urinals, showers', 'Internal & external water supply', 'Soil, waste and sub-soil drainage', 'Hydro-pneumatic systems, WTP, ETP & STP works', 'Rain and storm water systems, recharge pits', 'Pipes: UPVC, CPVC, PPR, GI, CI/DI, stainless steel, HDPE']
    },
    {
      id: 'testing', title: 'Testing & Commissioning', tag: 'Proven before handover', img: 'site/img/gallery/g99.jpg', size: 'md', color: 'amber',
      short: 'Test, start-up and maintenance for substations, generators, drives and switchgear.',
      intro: 'A wide range of tools for routine testing, including resistance and inductance meters, temperature gauges and electrical testing.',
      list: ['Low, medium & high voltage power systems and substations', 'Grounding system testing, protective relay calibration', 'Circuit breaker, transformer & switchgear testing', 'Primary current injection, AC/DC hi-pot, tan delta', 'Infrared and oil & gas analysis', 'Substation inspections and battery maintenance']
    },
    {
      id: 'sectors', title: 'Where we work', tag: 'Sectors', img: 'site/img/banner2.jpg', size: 'wide', color: 'fire',
      short: 'Metros, power plants, IT parks, hospitals, townships and MIVAN high-rises.',
      intro: 'The kinds of projects our teams execute today.',
      list: ['Metro stations & depots', 'Educational institutions', 'IT / SEZ', 'Pharma', 'Commercial & hospitality', 'High-rise residential, villas & row houses', 'MES and defence', 'Industrial, substations & power plants', 'Specialised: MIVAN / Aluform shuttering, precast concealed conduits']
    }
  ],

  powerpath: [
    { t: '33 kV HT line', v: 33000, img: 'site/img/gallery/g96.jpg', d: 'Power arrives from the utility at high tension. We lay the HT cables and terminations and build the incoming yard, up to 33 kV.' },
    { t: 'Transformer', v: 11000, img: 'site/img/gallery/g100.jpg', d: 'Transformers step the voltage down for the building. We install, test and commission them with their protection gear.' },
    { t: 'HT / LT panels', v: 433, img: 'site/img/gallery/g58.jpg', d: 'Incomers, breakers and distribution panels, many built in our own panel factory at Yalavarti Engineering.' },
    { t: 'Rising mains & bus duct', v: 415, img: 'site/img/gallery/g101.jpg', d: 'Copper and aluminium bus ducts and rising mains carry power up the tower, floor by floor.' },
    { t: 'Cable trays & DBs', v: 240, img: 'site/img/gallery/g72.jpg', d: 'Trays, raceways and distribution boards route every circuit to where it is needed.' },
    { t: 'Point of use', v: 230, img: 'site/img/gallery/g55.jpg', d: 'Lighting, sockets, UPS, CCTV and BMS. The last switch, tested and handed over.' }
  ],

  timeline: [
    { y: '1998', t: 'Cyber Towers', d: 'The start. External electrification and automation at Hyderabad\'s landmark IT tower, under L&T.', img: 'site/img/banner1.jpg' },
    { y: '2002', t: '400 kV switchyards', d: 'Bhilai switchyard and HITEX, followed by the NTPC Nunna 400 kV extension in 2003.', img: 'site/img/gallery/g106.jpg' },
    { y: '2005', t: 'Microsoft & Cyber Pearl', d: 'External electrification for Hyderabad\'s growing IT corridor.', img: 'site/img/gallery/g63.jpg' },
    { y: '2008', t: 'First in MIVAN', d: 'Serene County-2. We became the first contractors to execute electrical works in MIVAN shuttering in Hyderabad, and later in Odisha.', img: 'site/img/cat3.jpg' },
    { y: '2012', t: 'Metro rail', d: 'Chennai Metro, then Bangalore Metro terminals and the Miyapur Metro depot.', img: 'site/img/banner2.jpg' },
    { y: '2016', t: 'Ekana Stadium & IIM Raipur', d: 'An international cricket stadium in Lucknow and a national institute campus, both with NCC.', img: 'site/img/banner3.jpg' },
    { y: '2017', t: '3×350 MW power plant', d: 'External electrical works at the Meenakshi power plant, Nellore, for Siemens.', img: 'site/img/gallery/g108.jpg' },
    { y: '2020', t: '₹200 crore year', d: '2,000 million rupees of orders in 2019–20. AIIMS Mangalagiri and IIT Hyderabad in progress.', img: 'site/img/cat2.jpg' },
    { y: '2022+', t: 'Skylines of Hyderabad', d: 'One Golden Mile, SAS The Crown, KRC Hetero and more across Kokapet and the financial district.', img: 'site/img/gallery/g62.jpg' }
  ],

  gallery: {
    Electrical: [55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 96, 97, 99, 100, 101, 102, 105, 106, 107, 108, 109],
    'Fire fighting': [78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 115, 117, 118, 119, 120, 122, 123, 125, 127],
    Panels: [94, 95, 110, 111],
    PHE: [88, 89, 90, 91, 92, 112, 113, 114]
  },

  clientLogos: ['c16.png', 'c17.png', 'c18.jpg', 'c19.jpg', 'c20.jpg', 'c21.jpg', 'c22.jpg', 'c23.jpg', 'c24.jpg', 'c25.jpg', 'c26.jpg', 'c27.jpg', 'c28.jpg', 'c29.jpg', 'c30.jpg', 'c31.jpg', 'c32.jpg', 'c33.jpg', 'c34.jpg', 'c35.png', 'c36.jpg', 'c37.png', 'c38.png', 'c39.jpg', 'c40.jpg', 'c41.png', 'c42.jpg', 'c44.jpg', 'c45.jpg', 'c46.png', 'c47.jpg', 'c48.jpg', 'c49.jpg', 'c50.jpg'],

  brands: ['Legrand', 'Schneider', 'ABB', 'Hager', 'MK', 'Wipro', 'Kirloskar', 'Polycab', 'Lapp', 'RR Kabel', 'Finolex', 'Havells', '3M', 'Dowells', 'Jindal', 'KEI', 'Amara Raja', 'HPL', 'Socomec', 'Prince', 'Astral', 'Ashirvad', 'Supreme', 'Zoloto', 'Indo Asian', 'Universal', 'Nelco', 'VIP', 'AKG', 'Newage'],

  // lon, lat
  places: [
    { n: 'Hyderabad', k: 'hq', p: [78.47, 17.38], note: 'Corporate office · Kondapur' },
    { n: 'Chennai', k: 'br', p: [80.27, 13.08], note: 'Branch · Chennai Metro, Park-63' },
    { n: 'Bengaluru', k: 'br', p: [77.59, 12.97], note: 'Branch · Bangalore Metro, DAN Hotel' },
    { n: 'Bhubaneswar', k: 'br', p: [85.82, 20.3], note: 'Branch · Odisha projects' },
    { n: 'Noida', k: 'br', p: [77.39, 28.54], note: 'Branch · North India' },
    { n: 'Nagpur', k: 'br', p: [79.09, 21.15], note: 'Branch · DG MAP Nagpur' },
    { n: 'Jammu', k: 'br', p: [74.86, 32.73], note: 'Branch · Mini township' },
    { n: 'Lucknow', k: 'site', p: [80.95, 26.85], note: 'Ekana International Cricket Stadium' },
    { n: 'Naya Raipur', k: 'site', p: [81.78, 21.16], note: 'IIM Raipur campus' },
    { n: 'Bhilai', k: 'site', p: [81.38, 21.19], note: '400 kV switchyard' },
    { n: 'Mumbai', k: 'site', p: [72.88, 19.08], note: 'Omkar Projects' },
    { n: 'Pune', k: 'site', p: [73.86, 18.52], note: 'Explosion Testing Centre' },
    { n: 'Jharsuguda', k: 'site', p: [84.01, 21.86], note: 'Vedanta township (Aluform)' },
    { n: 'Koraput', k: 'site', p: [82.71, 18.81], note: 'Govt. Medical College' },
    { n: 'Visakhapatnam', k: 'site', p: [83.22, 17.69], note: 'APTIDCO · Iconica Grande' },
    { n: 'Amaravati / Guntur', k: 'site', p: [80.45, 16.4], note: 'AIIMS Mangalagiri · APCRDA · SRM' },
    { n: 'Nellore', k: 'site', p: [79.99, 14.44], note: '3×350 MW Meenakshi power plant' },
    { n: 'Raichur', k: 'site', p: [77.36, 16.2], note: 'Raychem Medicare' },
    { n: 'Tiruchi', k: 'site', p: [78.7, 10.8], note: 'Omega' }
  ],

  // Rough outline of India (lon, lat) used to draw the dot map.
  india: [[74.6,37],[76.8,35.8],[78.3,35.5],[79.3,33],[78.9,31.4],[80.2,30.4],[81,30.2],[82.3,28.8],[84,27.5],[85.8,26.7],[88.1,26.4],[88.2,27.9],[88.8,27.3],[89.8,26.8],[92,26.8],[92.1,27.8],[94.2,29.2],[96.1,29.4],[97.3,28.3],[96.3,27.3],[95.2,26.6],[94.6,25.3],[94.2,23.8],[93.4,22.3],[92.6,22],[92.3,23.6],[91.7,22.9],[91.2,23.7],[91.9,24.9],[90,25.2],[89.8,26],[88.5,26.2],[88.2,25.2],[88.7,24.3],[88.7,23],[89,21.9],[87.9,21.6],[87,21.4],[86.8,20.5],[85.8,19.8],[84.8,19.2],[84,18.3],[82.4,17],[81.3,16.3],[80.2,15.4],[80.3,13.4],[79.9,11.9],[79.8,10.3],[79.2,9.3],[78.2,8.9],[77.5,8.1],[76.6,8.9],[76.1,10.4],[75.7,11.6],[74.9,12.9],[74.4,14.6],[73.8,15.9],[73.1,17.6],[72.8,19.1],[72.9,20.6],[72.6,21.4],[72.2,21.1],[70.9,20.8],[69.3,22.3],[68.5,23.6],[69.6,24.3],[71.1,24.4],[70.3,25.6],[70.1,26.6],[69.6,27.1],[70.4,28],[71.8,27.9],[72.9,29.5],[73.9,30.4],[74.6,31.1],[75.3,32.3],[74.5,32.9],[74,33.6],[74.3,34.6],[73.8,34.8],[74.6,37]]
}

export const PLAN_TYPES = SITE.plan.types as PlanType[]
export const PLACES = SITE.places as Place[]
