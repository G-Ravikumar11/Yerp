/** Every state and union territory of India, by the code the GST returns use (the first two digits of a GSTIN), A to Z. The
 * server sends the same list with the expense heads; this is what the form falls back on when an older answer has none. */
export const INDIAN_STATES: { value: string; label: string }[] = [
  ['35', 'Andaman & Nicobar'], ['37', 'Andhra Pradesh'], ['12', 'Arunachal Pradesh'], ['18', 'Assam'], ['10', 'Bihar'], ['04', 'Chandigarh'],
  ['22', 'Chhattisgarh'], ['26', 'Dadra & Nagar Haveli and Daman & Diu'], ['07', 'Delhi'], ['30', 'Goa'], ['24', 'Gujarat'], ['06', 'Haryana'],
  ['02', 'Himachal Pradesh'], ['01', 'Jammu & Kashmir'], ['20', 'Jharkhand'], ['29', 'Karnataka'], ['32', 'Kerala'], ['38', 'Ladakh'],
  ['31', 'Lakshadweep'], ['23', 'Madhya Pradesh'], ['27', 'Maharashtra'], ['14', 'Manipur'], ['17', 'Meghalaya'], ['15', 'Mizoram'],
  ['13', 'Nagaland'], ['21', 'Odisha'], ['34', 'Puducherry'], ['03', 'Punjab'], ['08', 'Rajasthan'], ['11', 'Sikkim'], ['33', 'Tamil Nadu'],
  ['36', 'Telangana'], ['16', 'Tripura'], ['09', 'Uttar Pradesh'], ['05', 'Uttarakhand'], ['19', 'West Bengal'],
].map(([value, label]) => ({ value, label }))
