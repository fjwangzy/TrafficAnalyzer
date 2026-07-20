const FLOW_PATHS = [
  { id: 'northbound', path: 'M 245 600 C 245 450, 248 380, 250 310 C 252 250, 248 180, 245 0', color: '#5ad3e7', duration: '4s', begin: '0s' },
  { id: 'eastbound-turn', path: 'M 255 600 C 255 440, 280 360, 340 320 C 400 280, 450 290, 500 295', color: '#5ad3e7', duration: '3.5s', begin: '-1.7s' },
  { id: 'southbound-turn', path: 'M 0 305 C 100 305, 180 320, 240 350 C 270 370, 260 440, 255 600', color: '#a688ff', duration: '4.2s', begin: '-.8s' },
  { id: 'westbound-turn', path: 'M 240 0 C 240 150, 220 250, 170 290 C 120 320, 60 315, 0 310', color: '#a688ff', duration: '3.8s', begin: '-1.2s' },
  { id: 'reverse-turn', path: 'M 500 335 C 400 335, 310 320, 270 280 C 250 250, 250 150, 255 0', color: '#54d89b', duration: '4.5s', begin: '-.3s' },
  { id: 'diagonal', path: 'M 0 560 C 120 480, 200 380, 260 310 C 320 240, 400 150, 500 40', color: '#54d89b', duration: '5s', begin: '-2.1s' },
]

export function LoginTrafficFlow() {
  return (
    <svg
      className='login-traffic-flow'
      viewBox='0 0 500 600'
      preserveAspectRatio='xMidYMid slice'
      aria-hidden='true'
      focusable='false'
      data-testid='login-traffic-flow'
    >
      <defs>
        <path id='login-road-surface' d='M 212 0 L 288 0 L 288 272 L 500 272 L 500 348 L 288 348 L 288 600 L 212 600 L 212 348 L 0 348 L 0 272 L 212 272 Z' />
        <path id='login-road-edge' d='M 212 0 L 212 272 L 0 272 M 288 0 L 288 272 L 500 272 M 212 600 L 212 348 L 0 348 M 288 600 L 288 348 L 500 348' />
        {FLOW_PATHS.map((flow) => <path key={flow.id} id={`login-flow-${flow.id}`} d={flow.path} fill='none' />)}
      </defs>

      <g className='login-flow-grid'>
        {Array.from({ length: 10 }, (_, index) => <line key={`row-${index}`} x1='0' y1={index * 66} x2='500' y2={index * 66} />)}
        {Array.from({ length: 8 }, (_, index) => <line key={`column-${index}`} x1={index * 71} y1='0' x2={index * 71} y2='600' />)}
      </g>

      <use href='#login-road-surface' className='login-flow-road' />
      <use href='#login-road-edge' className='login-flow-road-edge' />
      <polygon points='212,272 288,272 288,348 212,348' className='login-flow-intersection' />
      <g className='login-flow-lanes'>
        <line x1='250' y1='20' x2='250' y2='270' />
        <line x1='250' y1='350' x2='250' y2='580' />
        <line x1='20' y1='310' x2='210' y2='310' />
        <line x1='290' y1='310' x2='480' y2='310' />
      </g>

      {FLOW_PATHS.map((flow) => (
        <g key={`trail-${flow.id}`}>
          <use href={`#login-flow-${flow.id}`} stroke={flow.color} className='login-flow-trail-glow' />
          <use href={`#login-flow-${flow.id}`} stroke={flow.color} className='login-flow-trail' />
        </g>
      ))}

      <g className='login-flow-motion'>
        {FLOW_PATHS.map((flow) => (
          <g key={`particle-${flow.id}`}>
            <circle r='3' fill={flow.color} className='login-flow-particle'>
              <animateMotion dur={flow.duration} begin={flow.begin} repeatCount='indefinite'><mpath href={`#login-flow-${flow.id}`} /></animateMotion>
            </circle>
            <circle r='8' fill={flow.color} className='login-flow-particle-glow'>
              <animateMotion dur={flow.duration} begin={flow.begin} repeatCount='indefinite'><mpath href={`#login-flow-${flow.id}`} /></animateMotion>
            </circle>
          </g>
        ))}
      </g>

      <circle cx='250' cy='310' r='40' className='login-flow-detection' />
      <circle cx='250' cy='310' r='65' className='login-flow-detection delayed' />
      <g className='login-flow-labels'>
        <text x='265' y='470'>P-01 → 32km/h</text>
        <text x='365' y='278'>P-02 → 28km/h</text>
        <text x='105' y='362'>P-03 ← 24km/h</text>
        <text x='260' y='238'>36.672°N 116.997°E</text>
        <text x='250' y='325' textAnchor='middle' className='login-flow-zone-label'>DETECTION ZONE</text>
        <text x='425' y='20' textAnchor='end'>LIVE</text>
        <circle cx='435' cy='17' r='2' className='login-flow-live' />
      </g>
    </svg>
  )
}
