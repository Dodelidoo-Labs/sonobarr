let return_to_top = document.getElementById('return-to-top');

let lidarr_get_artists_button = document.getElementById(
	'lidarr-get-artists-button'
);
let start_stop_button = document.getElementById('start-stop-button');
let lidarr_status = document.getElementById('lidarr-status');
let lidarr_spinner = document.getElementById('lidarr-spinner');
let load_more_button = document.getElementById('load-more-btn');
let header_spinner = document.getElementById('artists-loading-spinner');

let lidarr_item_list = document.getElementById('lidarr-item-list');
let lidarr_select_all_checkbox = document.getElementById('lidarr-select-all');
let lidarr_select_all_container = document.getElementById(
	'lidarr-select-all-container'
);

let config_modal = document.getElementById('config-modal');
let lidarr_sidebar = document.getElementById('lidarr-sidebar');

const START_LABEL = 'Start discovery';
const STOP_LABEL = 'Stop';

let save_message = document.getElementById('save-message');
let save_changes_button = document.getElementById('save-changes-button');
let settings_form = document.getElementById('settings-form');
const lidarr_address = document.getElementById('lidarr-address');
const lidarr_api_key = document.getElementById('lidarr-api-key');
const root_folder_path = document.getElementById('root-folder-path');
const youtube_api_key = document.getElementById('youtube-api-key');
const openai_api_key_input = document.getElementById('openai-api-key');
const openai_api_base_input = document.getElementById('openai-api-base');
const openai_model_input = document.getElementById('openai-model');
const openai_extra_headers_input = document.getElementById(
	'openai-extra-headers'
);
const openai_max_seed_artists_input = document.getElementById(
	'openai-max-seed-artists'
);
const similar_artist_batch_size_input = document.getElementById(
	'similar-artist-batch-size'
);
const quality_profile_id_input = document.getElementById('quality-profile-id');
const metadata_profile_id_input = document.getElementById(
	'metadata-profile-id'
);
const lidarr_api_timeout_input = document.getElementById('lidarr-api-timeout');
const fallback_to_top_result_checkbox = document.getElementById(
	'fallback-to-top-result'
);
const search_for_missing_albums_checkbox = document.getElementById(
	'search-for-missing-albums'
);
const dry_run_adding_to_lidarr_checkbox = document.getElementById(
	'dry-run-adding-to-lidarr'
);
const lidarr_monitor_option_select = document.getElementById(
	'lidarr-monitor-option'
);
const lidarr_monitor_new_items_select = document.getElementById(
	'lidarr-monitor-new-items'
);
const lidarr_monitored_checkbox = document.getElementById('lidarr-monitored');
const lidarr_albums_to_monitor_input = document.getElementById(
	'lidarr-albums-to-monitor'
);
const auto_start_checkbox = document.getElementById('auto-start');
const auto_start_delay_input = document.getElementById('auto-start-delay');
const last_fm_api_key_input = document.getElementById('last-fm-api-key');
const last_fm_api_secret_input = document.getElementById('last-fm-api-secret');
const api_key_input = document.getElementById('api-key');

const personalLastfmButton = document.getElementById('personal-lastfm-button');
const personalLastfmSpinner = document.getElementById(
	'personal-lastfm-spinner'
);
const personalLastfmHint = document.getElementById('personal-lastfm-hint');
const personalListenbrainzButton = document.getElementById(
	'personal-listenbrainz-button'
);
const personalListenbrainzSpinner = document.getElementById(
	'personal-listenbrainz-spinner'
);
const personalListenbrainzHint = document.getElementById(
	'personal-listenbrainz-hint'
);

const personalDiscoveryServices = {
	lastfm: {
		label: 'Last.fm',
		button: personalLastfmButton,
		spinner: personalLastfmSpinner,
		hint: personalLastfmHint,
		readyTitle: 'Stream recommendations from your Last.fm profile.',
		readyHint: 'Ready to use your Last.fm listening history.',
	},
	listenbrainz: {
		label: 'ListenBrainz',
		button: personalListenbrainzButton,
		spinner: personalListenbrainzSpinner,
		hint: personalListenbrainzHint,
		readyTitle: 'Stream ListenBrainz weekly exploration picks.',
		readyHint: 'Ready to use ListenBrainz weekly exploration.',
	},
};

function getPersonalServiceLabel(source) {
	if (!source) {
		return 'Personal discovery';
	}
	let controls = personalDiscoveryServices[source];
	if (controls?.label) {
		return controls.label;
	}
	let fallback = String(source).replaceAll(/[_-]+/g, ' ').trim();
	if (!fallback) {
		return 'Personal discovery';
	}
	return fallback.charAt(0).toUpperCase() + fallback.slice(1);
}

function getPersonalServiceTitle(source) {
	let label = getPersonalServiceLabel(source);
	return label === 'Personal discovery' ? label : label + ' discovery';
}

const ai_assist_button = document.getElementById('ai-assist-button');
const ai_helper_modal = document.getElementById('ai-helper-modal');
const ai_helper_form = document.getElementById('ai-helper-form');
const ai_helper_input = document.getElementById('ai-helper-input');
const ai_helper_error = document.getElementById('ai-helper-error');
const ai_helper_results = document.getElementById('ai-helper-results');
const ai_helper_submit = document.getElementById('ai-helper-submit');
const ai_helper_spinner = document.getElementById('ai-helper-spinner');

let lidarr_items = [];
let is_admin = false;
let can_add_without_approval = false;
let socket = io({
	withCredentials: true,
});

let personalSourcesState = null;
let personalDiscoveryState = {
	inFlight: false,
	source: null,
};

// Initial load flow control
let initialLoadComplete = false;
let initialLoadHasMore = false;
let loadMorePending = false;

if (ai_helper_modal) {
	ai_helper_modal.addEventListener('hidden.bs.modal', function () {
		if (ai_helper_input) {
			ai_helper_input.value = '';
		}
		reset_ai_feedback();
		set_ai_form_loading(false);
		if (ai_helper_submit) {
			ai_helper_submit.blur();
		}
	});
}

if (ai_helper_form) {
	ai_helper_form.addEventListener('submit', function (event) {
		event.preventDefault();
		if (!socket.connected) {
			show_toast('Connection Lost', 'Please reconnect to continue.');
			return;
		}
		if (!ai_helper_input) {
			return;
		}
		let prompt = ai_helper_input.value.trim();
		if (!prompt) {
			if (ai_helper_error) {
				ai_helper_error.textContent =
					'Tell us what to search for before asking the AI assistant.';
				ai_helper_error.classList.remove('d-none');
			}
			return;
		}
		reset_ai_feedback();
		set_ai_form_loading(true);
		begin_ai_discovery_flow();
		socket.emit('ai_prompt_req', {
			prompt: prompt,
		});
	});
}

if (personalLastfmButton) {
	personalLastfmButton.addEventListener('click', function () {
		startPersonalDiscovery('lastfm');
	});
}

if (personalListenbrainzButton) {
	personalListenbrainzButton.addEventListener('click', function () {
		startPersonalDiscovery('listenbrainz');
	});
}

updatePersonalButtons();

socket.on('connect', function () {
	socket.emit('personal_sources_poll');
});

socket.on('user_info', function (data) {
	is_admin = data.is_admin || false;
	can_add_without_approval = data.can_add_without_approval || is_admin;
});

function show_header_spinner() {
	if (header_spinner) {
		header_spinner.classList.remove('d-none');
	}
}

function hide_header_spinner() {
	if (header_spinner) {
		header_spinner.classList.add('d-none');
	}
}

function escape_html(text) {
	if (text === null || text === undefined) {
		return '';
	}
	let div = document.createElement('div');
	div.textContent = text;
	return div.innerHTML;
}

function render_biography_html(biography) {
	if (typeof biography !== 'string') {
		return '';
	}
	let trimmed = biography.trim();
	if (!trimmed) {
		return '';
	}
	let containsHtml = /<\/?[a-z][\s\S]*>/i.test(trimmed);
	if (containsHtml) {
		let sanitizedHtml;
		if (typeof DOMPurify === 'undefined') {
			sanitizedHtml = escape_html(trimmed);
		} else {
			sanitizedHtml = DOMPurify.sanitize(trimmed, {
				USE_PROFILES: { html: true },
			});
		}
		if (
			sanitizedHtml &&
			!/<p[\s>]/i.test(sanitizedHtml) &&
			/\n/.test(sanitizedHtml)
		) {
			let htmlBlocks = sanitizedHtml
				.split(/\n{2,}/)
				.map(function (block) {
					return block.trim();
				})
				.filter(function (block) {
					return block.length > 0;
				})
				.map(function (block) {
					return '<p>' + block.replaceAll('\n', '<br>') + '</p>';
				})
				.join('');
			if (htmlBlocks) {
				return htmlBlocks;
			}
		}
		return sanitizedHtml;
	}
	let paragraphs = trimmed
		.split(/\n{2,}/)
		.map(function (block) {
			return block.trim();
		})
		.filter(function (block) {
			return block.length > 0;
		})
		.map(function (block) {
			return '<p>' + escape_html(block).replaceAll('\n', '<br>') + '</p>';
		})
		.join('');
	if (!paragraphs) {
		return escape_html(trimmed);
	}
	if (typeof DOMPurify !== 'undefined') {
		return DOMPurify.sanitize(paragraphs, {
			USE_PROFILES: { html: true },
		});
	}
	return paragraphs;
}

function render_loading_spinner(message) {
	return `
        <div class="d-flex justify-content-center align-items-center py-4">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">${message}</span>
            </div>
        </div>
    `;
}

function reset_ai_feedback() {
	if (ai_helper_error) {
		ai_helper_error.textContent = '';
		ai_helper_error.classList.add('d-none');
	}
	if (ai_helper_results) {
		ai_helper_results.innerHTML = '';
		ai_helper_results.classList.add('d-none');
	}
}

function set_ai_form_loading(isLoading) {
	if (ai_helper_submit) {
		ai_helper_submit.disabled = isLoading;
	}
	if (ai_helper_spinner) {
		if (isLoading) {
			ai_helper_spinner.classList.remove('d-none');
		} else {
			ai_helper_spinner.classList.add('d-none');
		}
	}
}

function begin_ai_discovery_flow() {
	clear_all();
	show_header_spinner();
}

function set_hint_text(element, message) {
	if (!element) {
		return;
	}
	let hasMessage = Boolean(message?.trim());
	element.textContent = hasMessage ? message : '';
	if (hasMessage) {
		element.classList.remove('d-none');
	} else {
		element.classList.add('d-none');
	}
}

function updatePersonalButtons() {
	let state = personalSourcesState || {};
	let isBusy = personalDiscoveryState.inFlight;
	Object.keys(personalDiscoveryServices).forEach(function (source) {
		let controls = personalDiscoveryServices[source];
		if (!controls?.button) {
			return;
		}
		let button = controls.button;
		let serviceState = state[source] || null;
		if (!serviceState) {
			button.disabled = true;
			button.title = 'Loading availability...';
			set_hint_text(controls.hint, '');
			return;
		}
		let label = getPersonalServiceLabel(source);
		let enabled = !!serviceState.enabled;
		let loading = isBusy && personalDiscoveryState.source === source;
		let readyTitle =
			controls.readyTitle || 'Stream personalised recommendations.';
		if (loading) {
			button.title = 'Personal discovery in progress...';
		} else if (enabled) {
			button.title = readyTitle;
		} else {
			button.title = serviceState.reason || readyTitle;
		}
		button.disabled = !enabled || isBusy;
		if (enabled) {
			let readyMessage = '';
			if (serviceState.username) {
				readyMessage =
					'Ready with ' +
					label +
					' profile ' +
					serviceState.username +
					'.';
			} else if (controls.readyHint) {
				readyMessage = controls.readyHint;
			} else {
				readyMessage =
					'Ready to use your ' +
					label.toLowerCase() +
					' listening history.';
			}
			set_hint_text(controls.hint, readyMessage);
		} else {
			set_hint_text(controls.hint, serviceState.reason || '');
		}
	});
}

function setPersonalDiscoveryLoading(source, isLoading) {
	let previousSource = personalDiscoveryState.source;
	personalDiscoveryState.inFlight = !!isLoading;
	personalDiscoveryState.source = isLoading ? source : null;
	let activeSource = isLoading ? source : previousSource;
	Object.keys(personalDiscoveryServices).forEach(function (name) {
		let controls = personalDiscoveryServices[name];
		if (!controls) {
			return;
		}
		if (controls.spinner) {
			controls.spinner.classList.toggle(
				'd-none',
				!(personalDiscoveryState.inFlight && activeSource === name)
			);
		}
		if (isLoading && name === source && controls.button) {
			controls.button.blur();
		}
	});
	updatePersonalButtons();
}

function startPersonalDiscovery(source) {
	if (!socket.connected) {
		show_toast('Connection Lost', 'Please reconnect to continue.');
		return;
	}
	if (!personalSourcesState) {
		show_toast(
			'Personal discovery',
			'Hang tight while we load your personal listening services.'
		);
		socket.emit('personal_sources_poll');
		return;
	}
	let sourceState = personalSourcesState[source];
	if (!sourceState?.enabled) {
		let reason = sourceState?.reason;
		let serviceTitle = getPersonalServiceTitle(source);
		show_toast(
			serviceTitle,
			reason ||
				'Configure this service in your profile to unlock personal picks.'
		);
		return;
	}
	begin_ai_discovery_flow();
	setPersonalDiscoveryLoading(source, true);
	socket.emit('user_recs_req', { source: source });
}

function show_modal_with_lock(modalId, onHidden) {
	let modalEl = document.getElementById(modalId);
	if (!modalEl) {
		return null;
	}
	let scrollbarWidth =
		globalThis.innerWidth - document.documentElement.clientWidth;
	document.body.style.overflow = 'hidden';
	document.body.style.paddingRight = `${scrollbarWidth}px`;
	let modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
	let hiddenHandler = function () {
		document.body.style.overflow = 'auto';
		document.body.style.paddingRight = '0';
		modalEl.removeEventListener('hidden.bs.modal', hiddenHandler);
		if (typeof onHidden === 'function') {
			onHidden();
		}
	};
	modalEl.addEventListener('hidden.bs.modal', hiddenHandler, { once: true });
	modalInstance.show();
	return modalInstance;
}

function ensure_audio_modal_visible() {
	let modalEl = document.getElementById('audio-player-modal');
	if (!modalEl) {
		return;
	}
	if (!modalEl.classList.contains('show')) {
		show_modal_with_lock('audio-player-modal', function () {
			let container = document.getElementById('audio-player-modal-body');
			if (container) {
				container.innerHTML = '';
			}
		});
	}
}

function show_audio_modal_loading(artistName) {
	let bodyEl = document.getElementById('audio-player-modal-body');
	let titleEl = document.getElementById('audio-player-modal-label');
	if (titleEl) {
		titleEl.textContent = `Fetching sample for ${artistName}`;
	}
	if (bodyEl) {
		bodyEl.innerHTML = render_loading_spinner('Loading sample...');
	}
	ensure_audio_modal_visible();
}

function update_audio_modal_content(payload) {
	let bodyEl = document.getElementById('audio-player-modal-body');
	let titleEl = document.getElementById('audio-player-modal-label');
	let artistName = payload?.artist || '';
	let trackName = payload?.track || '';
	let fallbackTitle = artistName || trackName || 'Preview Player';

	if (titleEl) {
		titleEl.textContent =
			artistName && trackName ? `${artistName} – ${trackName}` : fallbackTitle;
	}

	if (!bodyEl) {
		ensure_audio_modal_visible();
		return;
	}

	if (payload?.videoId) {
		let safeVideoId = encodeURIComponent(payload.videoId);
		let safeTitle = escape_html(
			`${artistName || 'Unknown artist'} – ${
				trackName || 'Unknown track'
			}`
		);
		bodyEl.innerHTML = `
            <div class="ratio ratio-16x9">
                <iframe src="https://www.youtube.com/embed/${safeVideoId}?autoplay=1" title="${safeTitle}"
                    allow="autoplay; encrypted-media" allowfullscreen></iframe>
            </div>
        `;
		ensure_audio_modal_visible();
		return;
	}

	if (payload?.previewUrl) {
		let safePreviewUrl = encodeURI(payload.previewUrl);
		let sourceLabel =
			payload.source === 'itunes' ? 'Preview via Apple Music' : 'Audio preview';
		bodyEl.innerHTML = `
	            <div>
	                <audio controls autoplay class="w-100" src="${safePreviewUrl}">
	                    Your browser does not support audio playback.
	                </audio>
	                <p class="mt-2 mb-0 text-muted small">${escape_html(
						sourceLabel
					)}</p>
	            </div>
	        `;
		ensure_audio_modal_visible();
		return;
	}

	bodyEl.innerHTML = `<div class="alert alert-warning mb-0">${escape_html(
		'Sample unavailable'
	)}</div>`;

	ensure_audio_modal_visible();
}

function show_audio_modal_error(message) {
	let bodyEl = document.getElementById('audio-player-modal-body');
	let titleEl = document.getElementById('audio-player-modal-label');
	if (titleEl) {
		titleEl.textContent = 'Sample unavailable';
	}
	if (bodyEl) {
		let safeMessage = escape_html(message);
		bodyEl.innerHTML = `<div class="alert alert-warning mb-0">${safeMessage}</div>`;
	}
	ensure_audio_modal_visible();
}

function show_bio_modal_loading(artistName) {
	let titleEl = document.getElementById('bio-modal-title');
	let bodyEl = document.getElementById('modal-body');
	if (titleEl) {
		titleEl.textContent = artistName;
	}
	if (bodyEl) {
		bodyEl.innerHTML = render_loading_spinner('Loading biography...');
	}
	show_modal_with_lock('bio-modal-modal');
}

function check_if_all_selected() {
	let checkboxes = document.querySelectorAll('input[name="lidarr-item"]');
	let all_checked = true;
	for (let checkbox of checkboxes) {
		if (!checkbox.checked) {
			all_checked = false;
			break;
		}
	}
	lidarr_select_all_checkbox.checked = all_checked;
}

function load_lidarr_data(response) {
	let every_check_box = document.querySelectorAll(
		'input[name="lidarr-item"]'
	);
	if (response.Running) {
		start_stop_button.classList.remove('btn-success');
		start_stop_button.classList.add('btn-warning');
		start_stop_button.textContent = STOP_LABEL;
		every_check_box.forEach((item) => {
			item.disabled = true;
		});
		lidarr_select_all_checkbox.disabled = true;
		lidarr_get_artists_button.disabled = true;
	} else {
		start_stop_button.classList.add('btn-success');
		start_stop_button.classList.remove('btn-warning');
		start_stop_button.textContent = START_LABEL;
		every_check_box.forEach((item) => {
			item.disabled = false;
		});
		lidarr_select_all_checkbox.disabled = false;
		lidarr_get_artists_button.disabled = false;
	}
	check_if_all_selected();
}

function create_load_more_button() {
	if (!load_more_button) return;
	if (!initialLoadComplete || !initialLoadHasMore) {
		load_more_button.classList.add('d-none');
		load_more_button.disabled = false;
		return;
	}
	load_more_button.classList.remove('d-none');
	load_more_button.disabled = loadMorePending;
}

function remove_load_more_button() {
	if (!load_more_button) return;
	load_more_button.classList.add('d-none');
	load_more_button.disabled = false;
}

/**
 * Resolve a similarity label for an artist payload.
 * @param {Object} artist
 * @returns {string}
 */
function get_similarity_label(artist) {
	let similarityText = typeof artist.Similarity === 'string' ? artist.Similarity.trim() : '';
	if (similarityText.length > 0) {
		return similarityText;
	}
	let hasScore =
		typeof artist.SimilarityScore === 'number' &&
		!Number.isNaN(artist.SimilarityScore);
	if (!hasScore) {
		return '';
	}
	return `Similarity: ${(artist.SimilarityScore * 100).toFixed(1)}%`;
}

/**
 * Render similarity text on an artist card.
 * @param {Element} artist_col
 * @param {Object} artist
 * @returns {void}
 */
function apply_similarity_text(artist_col, artist) {
	let similarityEl = artist_col.querySelector('.similarity');
	if (!similarityEl) {
		return;
	}
	let label = get_similarity_label(artist);
	similarityEl.textContent = label;
	similarityEl.classList.toggle('d-none', label.length === 0);
}

/**
 * Render image or fallback letter avatar for an artist card.
 * @param {Element} artist_col
 * @param {Object} artist
 * @returns {void}
 */
function apply_artist_image(artist_col, artist) {
	let imageContainer = artist_col.querySelector('.artist-img-container');
	if (!imageContainer) {
		return;
	}
	imageContainer.classList.remove('artist-placeholder');
	let existingPlaceholder = imageContainer.querySelector('.artist-placeholder-letter');
	if (existingPlaceholder) {
		existingPlaceholder.remove();
	}
	let coverImage = imageContainer.querySelector('.card-img-top');
	if (artist.Img_Link && coverImage) {
		coverImage.src = artist.Img_Link;
		coverImage.alt = artist.Name;
		coverImage.classList.remove('d-none');
		return;
	}
	if (coverImage) {
		coverImage.remove();
	}
	imageContainer.classList.add('artist-placeholder');
	let placeholderSpan = document.createElement('span');
	placeholderSpan.className = 'artist-placeholder-letter';
	let firstLetter =
		typeof artist.Name === 'string' && artist.Name.length > 0
			? artist.Name.charAt(0).toUpperCase()
			: '?';
	placeholderSpan.textContent = firstLetter;
	imageContainer.appendChild(placeholderSpan);
}

/**
 * Apply button and status-dot state based on artist availability.
 * @param {HTMLButtonElement} add_button
 * @param {Element|null} statusDot
 * @param {string} status
 * @param {string} idleText
 * @param {boolean} resetLoading
 * @returns {void}
 */
function apply_artist_status(add_button, statusDot, status, idleText, resetLoading) {
	let statusValue = 'info';
	if (status === 'Added' || status === 'Already in Lidarr') {
		statusValue = 'success';
		add_button.classList.remove('btn-primary', 'btn-warning', 'btn-danger');
		add_button.classList.add('btn-secondary');
		add_button.disabled = true;
		add_button.textContent = status;
	} else if (status === 'Requested') {
		statusValue = 'warning';
		add_button.classList.remove('btn-primary', 'btn-danger');
		add_button.classList.add('btn-warning');
		add_button.disabled = true;
		add_button.textContent = 'Pending Approval';
	} else if (
		status === 'Failed to Add' ||
		status === 'Invalid Path' ||
		status === 'Rejected'
	) {
		statusValue = 'danger';
		add_button.classList.remove('btn-primary', 'btn-warning');
		add_button.classList.add('btn-danger');
		add_button.disabled = true;
		add_button.textContent = status;
	} else {
		add_button.disabled = false;
		add_button.classList.remove('btn-danger', 'btn-secondary', 'btn-warning');
		if (!add_button.classList.contains('btn-primary')) {
			add_button.classList.add('btn-primary');
		}
		add_button.textContent = idleText;
	}
	if (resetLoading) {
		add_button.dataset.loading = '';
	}
	if (statusDot) {
		statusDot.dataset.status = statusValue;
	}
}

/**
 * Append one artist card from the template payload.
 * @param {Element} artist_row
 * @param {HTMLTemplateElement} template
 * @param {Object} artist
 * @returns {void}
 */
function append_artist_card(artist_row, template, artist) {
	let clone = document.importNode(template.content, true);
	let artist_col = clone.querySelector('#artist-column');
	let cardEl = artist_col.querySelector('.artist-card');
	let statusDot = cardEl ? cardEl.querySelector('.led') : null;
	artist_col.querySelector('.card-title').textContent = artist.Name;
	artist_col.querySelector('.genre').textContent = artist.Genre;
	artist_col.querySelector('.followers').textContent = artist.Followers;
	artist_col.querySelector('.popularity').textContent = artist.Popularity;
	apply_similarity_text(artist_col, artist);
	apply_artist_image(artist_col, artist);

	let add_button = artist_col.querySelector('.add-to-lidarr-btn');
	add_button.dataset.defaultText = add_button.dataset.defaultText || add_button.textContent;
	if (can_add_without_approval) {
		add_button.textContent = add_button.dataset.defaultText;
		add_button.addEventListener('click', function () {
			add_to_lidarr(artist.Name, add_button);
		});
	} else {
		add_button.textContent = 'Request';
		add_button.addEventListener('click', function () {
			request_artist(artist.Name, add_button);
		});
	}
	artist_col.querySelector('.get-preview-btn').addEventListener('click', function () {
		preview_req(artist.Name);
	});
	artist_col.querySelector('.listen-sample-btn').addEventListener('click', function () {
		listenSampleReq(artist.Name);
	});
	apply_artist_status(add_button, statusDot, artist.Status, add_button.textContent, false);
	artist_row.appendChild(clone);
}

function append_artists(artists) {
	let artist_row = document.getElementById('artist-row');
	let template = document.getElementById('artist-template');
	if (!artist_row || !template) {
		return;
	}
	if (!initialLoadComplete) {
		remove_load_more_button();
	}
	artists.forEach(function (artist) {
		append_artist_card(artist_row, template, artist);
	});
	if (initialLoadComplete) {
		create_load_more_button();
	}
}

// Remove infinite scroll triggers
globalThis.removeEventListener('scroll', function () {});
globalThis.removeEventListener('touchmove', function () {});
globalThis.removeEventListener('touchend', function () {});

function add_to_lidarr(artist_name, buttonEl) {
	if (socket.connected) {
		if (buttonEl) {
			buttonEl.disabled = true;
			buttonEl.innerHTML =
				'<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Adding...';
			buttonEl.classList.remove('btn-primary', 'btn-danger');
			if (!buttonEl.classList.contains('btn-secondary')) {
				buttonEl.classList.add('btn-secondary');
			}
			buttonEl.dataset.loading = 'true';
		}
		socket.emit('adder', encodeURIComponent(artist_name));
	} else {
		show_toast('Connection Lost', 'Please reload to continue.');
	}
}

function request_artist(artist_name, buttonEl) {
	if (socket.connected) {
		if (buttonEl) {
			buttonEl.disabled = true;
			buttonEl.innerHTML =
				'<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Requesting...';
			buttonEl.classList.remove('btn-primary', 'btn-danger');
			if (!buttonEl.classList.contains('btn-secondary')) {
				buttonEl.classList.add('btn-secondary');
			}
			buttonEl.dataset.loading = 'true';
		}
		socket.emit('request_artist', encodeURIComponent(artist_name));
	} else {
		show_toast('Connection Lost', 'Please reload to continue.');
	}
}

function show_toast(header, message) {
	let toast_container = document.querySelector('.toast-container');
	let toast_template = document
		.getElementById('toast-template')
		.cloneNode(true);
	toast_template.classList.remove('d-none');

	toast_template.querySelector('.toast-header strong').textContent = header;
	toast_template.querySelector('.toast-body').textContent = message;
	toast_template.querySelector('.text-muted').textContent =
		new Date().toLocaleString();

	toast_container.appendChild(toast_template);

	let toast = new bootstrap.Toast(toast_template);
	toast.show();

	toast_template.addEventListener('hidden.bs.toast', function () {
		toast_template.remove();
	});
}

// Guard against null elements that only exist on main page (base.html)
// These elements aren't present on other pages like User Management or Profile
if (return_to_top) {
	return_to_top.addEventListener('click', function () {
		globalThis.scrollTo({ top: 0, behavior: 'smooth' });
	});
}

// Lidarr selection controls only exist on main page
if (lidarr_select_all_checkbox) {
	lidarr_select_all_checkbox.addEventListener('change', function () {
		let is_checked = this.checked;
		let checkboxes = document.querySelectorAll('input[name="lidarr-item"]');
		checkboxes.forEach(function (checkbox) {
			checkbox.checked = is_checked;
		});
	});
}

// Lidarr sync button only exists on main page
if (lidarr_get_artists_button) {
	lidarr_get_artists_button.addEventListener('click', function () {
		lidarr_get_artists_button.disabled = true;
		lidarr_spinner.classList.remove('d-none');
		lidarr_status.textContent = 'Accessing Lidarr API';
		lidarr_item_list.innerHTML = '';
		socket.emit('get_lidarr_artists');
	});
}

// Discovery control button only exists on main page
if (start_stop_button) {
	start_stop_button.addEventListener('click', function () {
		let running_state = start_stop_button.textContent.trim() === START_LABEL;
		if (running_state) {
			// Reset initial load state and show overlay until first results arrive
			initialLoadComplete = false;
			initialLoadHasMore = false;
		loadMorePending = false;
		show_header_spinner();
		remove_load_more_button();

		start_stop_button.classList.remove('btn-success');
		start_stop_button.classList.add('btn-warning');
		start_stop_button.textContent = STOP_LABEL;
		let checked_items = Array.from(
			document.querySelectorAll('input[name="lidarr-item"]:checked')
		).map((item) => item.value);
		document
			.querySelectorAll('input[name="lidarr-item"]')
			.forEach((item) => {
				item.disabled = true;
			});
		lidarr_get_artists_button.disabled = true;
		lidarr_select_all_checkbox.disabled = true;
		socket.emit('start_req', checked_items);
	} else {
		hide_header_spinner();

		start_stop_button.classList.add('btn-success');
		start_stop_button.classList.remove('btn-warning');
		start_stop_button.textContent = START_LABEL;
		document
			.querySelectorAll('input[name="lidarr-item"]')
			.forEach((item) => {
				item.disabled = false;
			});
			lidarr_get_artists_button.disabled = false;
			lidarr_select_all_checkbox.disabled = false;
			socket.emit('stop_req');
		}
	});
}

if (load_more_button) {
	load_more_button.addEventListener('click', function () {
		if (loadMorePending || load_more_button.disabled) {
			return;
		}
		loadMorePending = true;
		load_more_button.disabled = true;
		show_header_spinner();
		socket.emit('load_more_artists');
	});
}

/**
 * Read string value from a settings field.
 * @param {HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement|null} element
 * @returns {string}
 */
function read_setting_input(element) {
	return element ? element.value : '';
}

/**
 * Read boolean state from a settings checkbox.
 * @param {HTMLInputElement|null} element
 * @param {boolean} fallback
 * @returns {boolean}
 */
function read_setting_checkbox(element, fallback) {
	return element ? element.checked : fallback;
}

/**
 * Convert nullable setting values into assignable form values.
 * @param {unknown} value
 * @returns {string|number|boolean}
 */
function coerce_setting_value(value) {
	return value === undefined || value === null ? '' : value;
}

/**
 * Assign a value to a settings field while preserving empty defaults.
 * @param {HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement|null} element
 * @param {unknown} value
 * @returns {void}
 */
function set_setting_input(element, value) {
	if (element) {
		element.value = coerce_setting_value(value);
	}
}

function build_settings_payload() {
	return {
		lidarr_address: read_setting_input(lidarr_address),
		lidarr_api_key: read_setting_input(lidarr_api_key),
		root_folder_path: read_setting_input(root_folder_path),
		youtube_api_key: read_setting_input(youtube_api_key),
		openai_api_key: read_setting_input(openai_api_key_input),
		openai_api_base: read_setting_input(openai_api_base_input),
		openai_model: read_setting_input(openai_model_input),
		openai_extra_headers: read_setting_input(openai_extra_headers_input),
		openai_max_seed_artists: read_setting_input(openai_max_seed_artists_input),
		similar_artist_batch_size: read_setting_input(similar_artist_batch_size_input),
		quality_profile_id: read_setting_input(quality_profile_id_input),
		metadata_profile_id: read_setting_input(metadata_profile_id_input),
		lidarr_api_timeout: read_setting_input(lidarr_api_timeout_input),
		fallback_to_top_result: read_setting_checkbox(
			fallback_to_top_result_checkbox,
			false
		),
		search_for_missing_albums: read_setting_checkbox(
			search_for_missing_albums_checkbox,
			false
		),
		dry_run_adding_to_lidarr: read_setting_checkbox(
			dry_run_adding_to_lidarr_checkbox,
			false
		),
		lidarr_monitor_option: read_setting_input(lidarr_monitor_option_select),
		lidarr_monitor_new_items: read_setting_input(lidarr_monitor_new_items_select),
		lidarr_monitored: read_setting_checkbox(lidarr_monitored_checkbox, true),
		lidarr_albums_to_monitor: read_setting_input(lidarr_albums_to_monitor_input),
		auto_start: read_setting_checkbox(auto_start_checkbox, false),
		auto_start_delay: read_setting_input(auto_start_delay_input),
		last_fm_api_key: read_setting_input(last_fm_api_key_input),
		last_fm_api_secret: read_setting_input(last_fm_api_secret_input),
		api_key: read_setting_input(api_key_input),
	};
}

function populate_settings_form(settings) {
	if (!settings) {
		return;
	}

	set_setting_input(lidarr_address, settings.lidarr_address);
	set_setting_input(lidarr_api_key, settings.lidarr_api_key);
	set_setting_input(root_folder_path, settings.root_folder_path);
	set_setting_input(youtube_api_key, settings.youtube_api_key);
	set_setting_input(quality_profile_id_input, settings.quality_profile_id);
	set_setting_input(metadata_profile_id_input, settings.metadata_profile_id);
	set_setting_input(lidarr_api_timeout_input, settings.lidarr_api_timeout);
	set_setting_input(lidarr_monitor_option_select, settings.lidarr_monitor_option);
	set_setting_input(
		lidarr_monitor_new_items_select,
		settings.lidarr_monitor_new_items
	);
	set_setting_input(lidarr_albums_to_monitor_input, settings.lidarr_albums_to_monitor);
	set_setting_input(
		similar_artist_batch_size_input,
		settings.similar_artist_batch_size
	);
	set_setting_input(auto_start_delay_input, settings.auto_start_delay);
	set_setting_input(last_fm_api_key_input, settings.last_fm_api_key);
	set_setting_input(last_fm_api_secret_input, settings.last_fm_api_secret);
	set_setting_input(api_key_input, settings.api_key);
	set_setting_input(openai_api_key_input, settings.openai_api_key);
	set_setting_input(openai_api_base_input, settings.openai_api_base);
	set_setting_input(openai_model_input, settings.openai_model);
	set_setting_input(openai_extra_headers_input, settings.openai_extra_headers);
	set_setting_input(
		openai_max_seed_artists_input,
		settings.openai_max_seed_artists
	);

	if (fallback_to_top_result_checkbox) {
		fallback_to_top_result_checkbox.checked = Boolean(
			settings.fallback_to_top_result
		);
	}
	if (search_for_missing_albums_checkbox) {
		search_for_missing_albums_checkbox.checked = Boolean(
			settings.search_for_missing_albums
		);
	}
	if (dry_run_adding_to_lidarr_checkbox) {
		dry_run_adding_to_lidarr_checkbox.checked = Boolean(
			settings.dry_run_adding_to_lidarr
		);
	}
	if (lidarr_monitored_checkbox) {
		lidarr_monitored_checkbox.checked =
			typeof settings.lidarr_monitored === 'boolean'
				? settings.lidarr_monitored
				: true;
	}
	if (auto_start_checkbox) {
		auto_start_checkbox.checked = Boolean(settings.auto_start);
	}
}

function handle_settings_saved(payload) {
	let message = payload?.message || 'Settings saved successfully.';
	if (save_changes_button) {
		save_changes_button.disabled = false;
	}
	if (save_message) {
		save_message.classList.remove('alert-danger');
		if (!save_message.classList.contains('alert-success')) {
			save_message.classList.add('alert-success');
		}
		save_message.classList.remove('d-none');
		save_message.textContent = message;
	}
	show_toast('Settings saved', message || 'Configuration updated successfully.');
}

function handle_settings_save_error(payload) {
	if (save_changes_button) {
		save_changes_button.disabled = false;
	}
	const message =
		payload?.message ||
		'Saving settings failed. Check the logs for more details.';
	if (save_message) {
		save_message.classList.remove('d-none', 'alert-success');
		save_message.classList.add('alert-danger');
		save_message.textContent = message;
	}
	show_toast('Settings error', message);
}

function reset_save_message() {
	if (!save_message) {
		return;
	}
	save_message.classList.add('d-none');
	save_message.classList.remove('alert-danger');
	if (!save_message.classList.contains('alert-success')) {
		save_message.classList.add('alert-success');
	}
	save_message.textContent = 'Settings saved successfully.';
}

if (settings_form && config_modal) {
	settings_form.addEventListener('submit', (event) => {
		event.preventDefault();
		if (!socket.connected) {
			show_toast('Connection Lost', 'Please reconnect to continue.');
			return;
		}
		reset_save_message();
		if (save_changes_button) {
			save_changes_button.disabled = true;
		}
		socket.emit('update_settings', build_settings_payload());
	});

	const handle_modal_show = () => {
		reset_save_message();
		if (save_changes_button) {
			save_changes_button.disabled = false;
		}
		socket.on('settingsLoaded', populate_settings_form);
		socket.emit('load_settings');
	};

	const handle_modal_hidden = () => {
		socket.off('settingsLoaded', populate_settings_form);
		reset_save_message();
		if (save_changes_button) {
			save_changes_button.disabled = false;
		}
	};

	config_modal.addEventListener('show.bs.modal', handle_modal_show);
	config_modal.addEventListener('hidden.bs.modal', handle_modal_hidden);

	socket.on('settingsSaved', handle_settings_saved);
	socket.on('settingsSaveError', handle_settings_save_error);
}

// Discovery sidebar only exists on main page
if (lidarr_sidebar) {
	lidarr_sidebar.addEventListener('show.bs.offcanvas', function (event) {
		socket.emit('side_bar_opened');
		socket.emit('personal_sources_poll');
	});
}

socket.on('lidarr_sidebar_update', (response) => {
	if (response.Status == 'Success') {
		lidarr_status.textContent = 'Lidarr List Retrieved';
		lidarr_items = response.Data;
		lidarr_item_list.innerHTML = '';
		lidarr_select_all_container.classList.remove('d-none');

		for (let i = 0; i < lidarr_items.length; i++) {
			let item = lidarr_items[i];

			let div = document.createElement('div');
			div.className = 'form-check';

			let input = document.createElement('input');
			input.type = 'checkbox';
			input.className = 'form-check-input';
			input.id = 'lidarr-' + i;
			input.name = 'lidarr-item';
			input.value = item.name;

			if (item.checked) {
				input.checked = true;
			}

			let label = document.createElement('label');
			label.className = 'form-check-label';
			label.htmlFor = 'lidarr-' + i;
			label.textContent = item.name;

			input.addEventListener('change', function () {
				check_if_all_selected();
			});

			div.appendChild(input);
			div.appendChild(label);

			lidarr_item_list.appendChild(div);
		}
	} else {
		lidarr_status.textContent = response.Code;
	}
	lidarr_get_artists_button.disabled = false;
	lidarr_spinner.classList.add('d-none');
	load_lidarr_data(response);
	if (!response.Running) {
		hide_header_spinner();
	}
});

socket.on('refresh_artist', (artist) => {
	let artist_cards = document.querySelectorAll('#artist-column');
	artist_cards.forEach(function (card) {
		let cardEl = card.querySelector('.artist-card');
		if (!cardEl) {
			return;
		}
		let titleEl = cardEl.querySelector('.card-title');
		let card_artist_name = titleEl ? titleEl.textContent.trim() : '';

		if (card_artist_name === artist.Name) {
			let add_button = cardEl.querySelector('.add-to-lidarr-btn');
			let statusDot = cardEl.querySelector('.led');
			let defaultText = add_button.dataset.defaultText || 'Add to Lidarr';
			apply_artist_status(
				add_button,
				statusDot,
				artist.Status,
				defaultText,
				true
			);
		}
	});
});

socket.on('more_artists_loaded', function (data) {
	append_artists(data);
});

socket.on('ai_prompt_ack', function (payload) {
	set_ai_form_loading(false);
	let seeds = Array.isArray(payload?.seeds) ? payload.seeds : [];
	if (seeds.length > 0) {
		let listItems = seeds
			.map(function (seed) {
				return `<li>${escape_html(seed)}</li>`;
			})
			.join('');
		if (ai_helper_results) {
			ai_helper_results.innerHTML = `<strong>AI picked these seed artists:</strong><ul class="mt-2 mb-0">${listItems}</ul>`;
			ai_helper_results.classList.remove('d-none');
		}
		show_toast(
			'AI Discovery',
			'Working from fresh seed artists suggested by the assistant.'
		);
	} else if (ai_helper_results) {
		ai_helper_results.textContent =
			"AI discovery started. We'll surface artists as soon as we find them.";
		ai_helper_results.classList.remove('d-none');
	}
});

socket.on('ai_prompt_error', function (payload) {
	set_ai_form_loading(false);
	let message = payload?.message || 'We could not complete the AI request right now.';
	if (ai_helper_error) {
		ai_helper_error.textContent = message;
		ai_helper_error.classList.remove('d-none');
	}
	hide_header_spinner();
	show_toast('AI Assistant', message);
});

socket.on('personal_sources_state', function (state) {
	personalSourcesState = state || {};
	updatePersonalButtons();
});

socket.on('user_recs_ack', function (payload) {
	let source = payload?.source ? String(payload.source).toLowerCase() : '';
	let username = payload?.username || '';
	let seeds = Array.isArray(payload?.seeds) ? payload.seeds : [];
	let title = getPersonalServiceTitle(source);
	let message = '';
	if (seeds.length > 0) {
		message = 'Streaming ' + seeds.length + ' picks';
		if (username) {
			message += ' for ' + username;
		}
		message += '.';
	} else {
		message = 'Working from fresh personal recommendations.';
	}
	show_toast(title, message);
});

socket.on('user_recs_error', function (payload) {
	let source = payload?.source ? String(payload.source).toLowerCase() : '';
	let message =
		payload?.message ||
		'We could not fetch your personal recommendations right now.';
	hide_header_spinner();
	setPersonalDiscoveryLoading(null, false);
	let title = getPersonalServiceTitle(source);
	show_toast(title, message);
});

// Server signals that initial batches are complete: show the Load More button now
socket.on('initial_load_complete', function (payload) {
	initialLoadComplete = true;
	initialLoadHasMore = Boolean(payload?.hasMore);
	loadMorePending = false;
	if (personalDiscoveryState.inFlight) {
		setPersonalDiscoveryLoading(null, false);
	}
	hide_header_spinner();
	if (initialLoadHasMore) {
		create_load_more_button();
	} else {
		remove_load_more_button();
	}
});

socket.on('load_more_complete', function (payload) {
	loadMorePending = false;
	initialLoadHasMore = Boolean(payload?.hasMore);
	hide_header_spinner();
	if (initialLoadHasMore) {
		create_load_more_button();
	} else {
		remove_load_more_button();
	}
});

socket.on('clear', function () {
	clear_all();
});

socket.on('new_toast_msg', function (data) {
	show_toast(data.title, data.message);
});

socket.on('disconnect', function () {
	show_toast('Connection Lost', 'Please reconnect to continue.');
	hide_header_spinner();
	personalSourcesState = null;
	setPersonalDiscoveryLoading(null, false);
	clear_all();
});

function clear_all() {
	let artist_row = document.getElementById('artist-row');
	let artist_cards = artist_row.querySelectorAll('#artist-column');
	artist_cards.forEach(function (card) {
		card.remove();
	});
	remove_load_more_button();
	initialLoadComplete = false;
	initialLoadHasMore = false;
	loadMorePending = false;
	// spinner state is controlled by the caller
}

let preview_request_flag = false;

function preview_req(artist_name) {
	if (!preview_request_flag) {
		preview_request_flag = true;
		show_bio_modal_loading(artist_name);
		socket.emit('preview_req', encodeURIComponent(artist_name));
		setTimeout(() => {
			preview_request_flag = false;
		}, 1500);
	}
}

socket.on('lastfm_preview', function (preview_info) {
	let modal_body = document.getElementById('modal-body');
	let modal_title = document.getElementById('bio-modal-title');
	let modalEl = document.getElementById('bio-modal-modal');

	if (typeof preview_info === 'string') {
		if (modal_body) {
			let safeMessage = escape_html(preview_info);
			modal_body.innerHTML = `<div class="alert alert-warning mb-0">${safeMessage}</div>`;
		}
		show_toast('Error Retrieving Bio', preview_info);
		if (modalEl && !modalEl.classList.contains('show')) {
			show_modal_with_lock('bio-modal-modal');
		}
		return;
	}

	let artist_name = preview_info.artist_name;
	let biography = preview_info.biography;
	if (modal_title) {
		modal_title.textContent = artist_name;
	}
	if (modal_body) {
		let biographyHtml = render_biography_html(biography);
		if (biographyHtml) {
			modal_body.innerHTML = biographyHtml;
		} else {
			modal_body.innerHTML =
				'<div class="alert alert-info mb-0">No formatted biography was returned for this artist.</div>';
		}
	}
	if (modalEl && !modalEl.classList.contains('show')) {
		show_modal_with_lock('bio-modal-modal');
	}
});

// Listen Sample button event
function listenSampleReq(artist_name) {
	show_audio_modal_loading(artist_name);
	socket.emit('prehear_req', encodeURIComponent(artist_name));
}

socket.on('prehear_result', function (data) {
	if (data?.videoId || data?.previewUrl) {
		update_audio_modal_content(data);
	} else {
		let message = data?.error || 'No YouTube or audio preview found.';
		show_audio_modal_error(message);
		show_toast('No sample found', message);
	}
});
