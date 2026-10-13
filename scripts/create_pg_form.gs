/**
 * create_pg_form.gs  (Google Apps Script)
 * ───────────────────────────────────────
 * Builds the "PG Details" Google Form used to collect REAL PG listings for the
 * PG Recommendation project, and links it to a response spreadsheet.
 *
 * How to use (about 2 minutes):
 *   1. Go to https://script.google.com  ->  New project
 *   2. Delete the default code, paste this whole file, press Save
 *   3. Pick `createPgForm` in the function dropdown  ->  Run
 *   4. Approve the permission prompt (it only touches Forms + Sheets in YOUR account)
 *   5. Open "Execution log": it prints the link to SHARE and the link to EDIT the form
 *
 * Design notes
 *   - Answers are dropdowns / Yes-No grids wherever possible so responses come
 *     back clean (no "yes", "Yes.", "yeah" variants to normalise later).
 *   - Rent is asked per sharing type because the dataset stores ONE ROW per
 *     (PG, sharing type): a PG with 2- and 3-sharing rooms becomes 2 rows.
 *   - Vacancy is asked per sharing type for the same reason.
 *   - No respondent email / name is collected.
 */

function createPgForm() {
  var form = FormApp.create('PG Details - Bangalore (College Project Data Collection)');

  form.setDescription(
    'Help us build a recommender with REAL PG data! Fill this for a PG you stay in, ' +
    'stayed in, or have visited. Takes ~3 minutes. Leave a rent blank if that ' +
    'sharing type does not exist. No personal details of yours are collected; ' +
    'responses are used only for an academic project.'
  );
  form.setCollectEmail(false);
  form.setAllowResponseEdits(false);
  form.setShowLinkToRespondAgain(true);   // so one person can add several PGs
  form.setProgressBar(true);
  form.setConfirmationMessage('Thank you! You can submit another PG using the link below.');

  var AREAS = [
    'Bagalur', 'Hebbal', 'Hennur', 'Horamavu', 'Jakkur', 'Kalyan Nagar',
    'Kammanahalli', 'Kodigehalli', 'Kothanur', 'Nagawara', 'RT Nagar',
    'Sahakar Nagar', 'Thanisandra', 'Vidyaranyapura', 'Yelahanka'
  ];

  // ── Page 1: basics ─────────────────────────────────────────────
  form.addSectionHeaderItem().setTitle('🏠 PG Details');

  form.addTextItem().setTitle('PG Name').setRequired(true);

  form.addParagraphTextItem()
      .setTitle('Full Address')
      .setHelpText('Building, street, landmark, pincode')
      .setRequired(true);

  form.addListItem()
      .setTitle('Area / Locality')
      .setHelpText('Pick the closest one. Choose "Other" if it is not listed.')
      .setChoiceValues(AREAS.concat(['Other (not in this list)']))
      .setRequired(true);

  form.addTextItem()
      .setTitle('Google Maps Link')
      .setHelpText('Open the PG in Google Maps -> Share -> Copy link. We use this to get exact location.')
      .setValidation(FormApp.createTextValidation().requireTextIsUrl().build())
      .setRequired(true);

  form.addMultipleChoiceItem()
      .setTitle('Gender')
      .setChoiceValues(['Boys', 'Girls', 'Co-ed'])
      .setRequired(true);

  // ── Page 2: rent ───────────────────────────────────────────────
  form.addPageBreakItem()
      .setTitle('💰 Rent & Sharing')
      .setHelpText('Monthly rent in ₹, numbers only (e.g. 8500). Leave BLANK if that sharing type is not offered. Fill at least one.');

  var rentCheck = FormApp.createTextValidation()
      .setHelpText('Enter a number between 1000 and 50000, or leave blank')
      .requireNumberBetween(1000, 50000)
      .build();

  ['1 Sharing (Single room) rent', '2 Sharing (Double) rent',
   '3 Sharing (Triple) rent', '4 Sharing rent'].forEach(function (title) {
    form.addTextItem().setTitle(title).setValidation(rentCheck);
  });

  form.addCheckboxItem()
      .setTitle('Which sharing types have a vacancy RIGHT NOW?')
      .setChoiceValues(['1 Sharing', '2 Sharing', '3 Sharing', '4 Sharing', 'None - fully occupied'])
      .setRequired(true);

  form.addDateItem()
      .setTitle('Next vacancy available from (if none right now)')
      .setHelpText('Optional')
      .setIncludesYear(true);

  // ── Page 3: food ───────────────────────────────────────────────
  form.addPageBreakItem().setTitle('🍽️ Food');

  form.addMultipleChoiceItem()
      .setTitle('Meals per day included in rent')
      .setChoiceValues(['0 (no food)', '1', '2', '3'])
      .setRequired(true);

  form.addMultipleChoiceItem()
      .setTitle('Food available on weekends?')
      .setChoiceValues(['Yes', 'No'])
      .setRequired(true);

  form.addMultipleChoiceItem()
      .setTitle('Food type')
      .setChoiceValues(['Veg', 'Non-Veg', 'Both'])
      .setRequired(true);

  form.addParagraphTextItem()
      .setTitle('Weekly food menu')
      .setHelpText('Optional - day-wise if you know it');

  // ── Page 4: facilities & rules ─────────────────────────────────
  form.addPageBreakItem().setTitle('🛠️ Facilities & Rules');

  form.addGridItem()
      .setTitle('Facilities available?')
      .setRows(['Wi-Fi', 'AC', 'Washing Machine / Laundry', 'Parking',
                'Housekeeping / Cleaning', 'Lift', 'Security guard', 'CCTV',
                'Power Backup', 'Drinking Water (RO / purified)'])
      .setColumns(['Yes', 'No'])
      .setRequired(true);

  form.addGridItem()
      .setTitle('Rules')
      .setRows(['Pets allowed', 'Visitors allowed', 'Smoking area available'])
      .setColumns(['Yes', 'No'])
      .setRequired(true);

  form.addMultipleChoiceItem()
      .setTitle('Curfew / Gate closing time')
      .setChoiceValues(['9 PM', '10 PM', '11 PM', 'No curfew'])
      .showOtherOption(true)
      .setRequired(true);

  form.addTextItem()
      .setTitle('Number of floors in the building')
      .setValidation(FormApp.createTextValidation()
          .setHelpText('Enter a whole number, e.g. 4')
          .requireNumberBetween(1, 40).build())
      .setRequired(true);

  // ── Page 5: provenance + notes ─────────────────────────────────
  form.addPageBreakItem().setTitle('📝 Last bits');

  form.addMultipleChoiceItem()
      .setTitle('How do you know this PG?')
      .setHelpText('Helps us note how reliable the data is')
      .setChoiceValues(['I currently live here', 'I lived here earlier',
                        'I visited / a friend lives here', 'I am the owner / manager'])
      .setRequired(true);

  form.addParagraphTextItem()
      .setTitle('Anything else worth knowing? (optional)')
      .setHelpText('Deposit amount, notice period, strict rules, what you liked / disliked...');

  // ── Responses -> spreadsheet ───────────────────────────────────
  var sheet = SpreadsheetApp.create('PG Details - Responses');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());

  // Newer Forms accounts create forms unpublished; harmless no-op on older ones.
  try { form.setPublished(true); } catch (e) { /* method not available */ }
  form.setAcceptingResponses(true);

  Logger.log('SHARE this link with friends : ' + form.getPublishedUrl());
  Logger.log('EDIT the form here           : ' + form.getEditUrl());
  Logger.log('Responses spreadsheet        : ' + sheet.getUrl());
}
