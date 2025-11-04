var return_to_top = document.getElementById('return-to-top');

var lidarr_get_artists_button = document.getElementById(
	'lidarr-get-artists-button'
);
var start_stop_button = document.getElementById('start-stop-button');
var lidarr_status = document.getElementById('lidarr-status');
var lidarr_spinner = document.getElementById('lidarr-spinner');
var load_more_button = document.getElementById('load-more-btn');
var header_spinner = document.getElementById('artists-loading-spinner');

var lidarr_item_list = document.getElementById('lidarr-item-list');
var lidarr_select_all_checkbox = document.getElementById('lidarr-select-all');
var lidarr_select_all_container = document.getElementById(
	'lidarr-select-all-container'
);

var config_modal = document.getElementById('config-modal');
var lidarr_sidebar = document.getElementById('lidarr-sidebar');

const START_LABEL = 'Start discovery';
const STOP_LABEL = 'Stop';

var save_message = document.getElementById('save-message');
var save_changes_button = document.getElementById('save-changes-button');
var settings_form = document.getElementById('settings-form');
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
	var controls = personalDiscoveryServices[source];
	if (controls && controls.label) {
		return controls.label;
	}
	var fallback = String(source).replace(/[_-]+/g, ' ').trim();
	if (!fallback) {
		return 'Personal discovery';
	}
	return fallback.charAt(0).toUpperCase() + fallback.slice(1);
}

function getPersonalServiceTitle(source) {
	var label = getPersonalServiceLabel(source);
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

var lidarr_items = [];
var is_admin = false;
var socket = io({
	withCredentials: true,
});

var personalSourcesState = null;
var personalDiscoveryState = {
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
		var prompt = ai_helper_input.value.trim();
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
	var div = document.createElement('div');
	div.textContent = text;
	return div.innerHTML;
}

function render_biography_html(biography) {
	if (typeof biography !== 'string') {
		return '';
	}
	var trimmed = biography.trim();
	if (!trimmed) {
		return '';
	}
	var containsHtml = /<\/?[a-z][\s\S]*>/i.test(trimmed);
	if (containsHtml) {
		var sanitizedHtml;
		if (typeof DOMPurify !== 'undefined') {
			sanitizedHtml = DOMPurify.sanitize(trimmed, {
				USE_PROFILES: { html: true },
			});
		} else {
			sanitizedHtml = escape_html(trimmed);
		}
		if (
			sanitizedHtml &&
			!/<p[\s>]/i.test(sanitizedHtml) &&
			/\n/.test(sanitizedHtml)
		) {
			var htmlBlocks = sanitizedHtml
				.split(/\n{2,}/)
				.map(function (block) {
					return block.trim();
				})
				.filter(function (block) {
					return block.length > 0;
				})
				.map(function (block) {
					return '<p>' + block.replace(/\n/g, '<br>') + '</p>';
				})
				.join('');
			if (htmlBlocks) {
				return htmlBlocks;
			}
		}
		return sanitizedHtml;
	}
	var paragraphs = trimmed
		.split(/\n{2,}/)
		.map(function (block) {
			return block.trim();
		})
		.filter(function (block) {
			return block.length > 0;
		})
		.map(function (block) {
			return '<p>' + escape_html(block).replace(/\n/g, '<br>') + '</p>';
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
	var hasMessage = !!(message && message.trim());
	element.textContent = hasMessage ? message : '';
	if (hasMessage) {
		element.classList.remove('d-none');
	} else {
		element.classList.add('d-none');
	}
}

function updatePersonalButtons() {
	var state = personalSourcesState || {};
	var isBusy = personalDiscoveryState.inFlight;
	Object.keys(personalDiscoveryServices).forEach(function (source) {
		var controls = personalDiscoveryServices[source];
		if (!controls || !controls.button) {
			return;
		}
		var button = controls.button;
		var serviceState = state[source] || null;
		if (!serviceState) {
			button.disabled = true;
			button.title = 'Loading availability...';
			set_hint_text(controls.hint, '');
			return;
		}
		var label = getPersonalServiceLabel(source);
		var enabled = !!serviceState.enabled;
		var loading = isBusy && personalDiscoveryState.source === source;
		var readyTitle =
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
			var readyMessage = '';
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
	var previousSource = personalDiscoveryState.source;
	personalDiscoveryState.inFlight = !!isLoading;
	personalDiscoveryState.source = isLoading ? source : null;
	var activeSource = isLoading ? source : previousSource;
	Object.keys(personalDiscoveryServices).forEach(function (name) {
		var controls = personalDiscoveryServices[name];
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
	var sourceState = personalSourcesState[source];
	var label = getPersonalServiceLabel(source);
	if (!sourceState || !sourceState.enabled) {
		var reason = sourceState && sourceState.reason;
		var serviceTitle = getPersonalServiceTitle(source);
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
	var modalEl = document.getElementById(modalId);
	if (!modalEl) {
		return null;
	}
	var scrollbarWidth =
		window.innerWidth - document.documentElement.clientWidth;
	document.body.style.overflow = 'hidden';
	document.body.style.paddingRight = `${scrollbarWidth}px`;
	var modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
	var hiddenHandler = function () {
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
	var modalEl = document.getElementById('audio-player-modal');
	if (!modalEl) {
		return;
	}
	if (!modalEl.classList.contains('show')) {
		show_modal_with_lock('audio-player-modal', function () {
			var container = document.getElementById('audio-player-modal-body');
			if (container) {
				container.innerHTML = '';
			}
		});
	}
}

function show_audio_modal_loading(artistName) {
	var bodyEl = document.getElementById('audio-player-modal-body');
	var titleEl = document.getElementById('audio-player-modal-label');
	if (titleEl) {
		titleEl.textContent = `Fetching sample for ${artistName}`;
	}
	if (bodyEl) {
		bodyEl.innerHTML = render_loading_spinner('Loading sample...');
	}
	ensure_audio_modal_visible();
}

function update_audio_modal_content(payload) {
	var bodyEl = document.getElementById('audio-player-modal-body');
	var titleEl = document.getElementById('audio-player-modal-label');
	var artistName = payload && payload.artist ? payload.artist : '';
	var trackName = payload && payload.track ? payload.track : '';

	if (titleEl) {
		if (artistName && trackName) {
			titleEl.textContent = `${artistName} – ${trackName}`;
		} else {
			titleEl.textContent = artistName || trackName || 'Preview Player';
		}
	}

	if (!bodyEl) {
		return;
	}

	if (payload && payload.videoId) {
		var safeVideoId = encodeURIComponent(payload.videoId);
		var safeTitle = escape_html(
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
	} else if (payload && payload.previewUrl) {
		var safePreviewUrl = encodeURI(payload.previewUrl);
		var sourceLabel =
			payload.source === 'itunes'
				? 'Preview via Apple Music'
				: 'Audio preview';
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
	} else {
		bodyEl.innerHTML = `<div class="alert alert-warning mb-0">${escape_html(
			'Sample unavailable'
		)}</div>`;
	}

	ensure_audio_modal_visible();
}

function show_audio_modal_error(message) {
	var bodyEl = document.getElementById('audio-player-modal-body');
	var titleEl = document.getElementById('audio-player-modal-label');
	if (titleEl) {
		titleEl.textContent = 'Sample unavailable';
	}
	if (bodyEl) {
		var safeMessage = escape_html(message);
		bodyEl.innerHTML = `<div class="alert alert-warning mb-0">${safeMessage}</div>`;
	}
	ensure_audio_modal_visible();
}

function show_bio_modal_loading(artistName) {
	var titleEl = document.getElementById('bio-modal-title');
	var bodyEl = document.getElementById('modal-body');
	if (titleEl) {
		titleEl.textContent = artistName;
	}
	if (bodyEl) {
		bodyEl.innerHTML = render_loading_spinner('Loading biography...');
	}
	show_modal_with_lock('bio-modal-modal');
}

function check_if_all_selected() {
	var checkboxes = document.querySelectorAll('input[name="lidarr-item"]');
	var all_checked = true;
	for (var i = 0; i < checkboxes.length; i++) {
		if (!checkboxes[i].checked) {
			all_checked = false;
			break;
		}
	}
	lidarr_select_all_checkbox.checked = all_checked;
}

function load_lidarr_data(response) {
	var every_check_box = document.querySelectorAll(
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

function append_artists(artists) {
	var artist_row = document.getElementById('artist-row');
	var template = document.getElementById('artist-template');
	if (!initialLoadComplete) {
		remove_load_more_button();
	}
	artists.forEach(function (artist) {
		var clone = document.importNode(template.content, true);
		var artist_col = clone.querySelector('#artist-column');
		var cardEl = artist_col.querySelector('.artist-card');
		var statusDot = cardEl ? cardEl.querySelector('.led') : null;
		var imageContainer = artist_col.querySelector('.artist-img-container');
		var coverImage = imageContainer
			? imageContainer.querySelector('.card-img-top')
			: null;

		artist_col.querySelector('.card-title').textContent = artist.Name;
		var similarityEl = artist_col.querySelector('.similarity');
		if (similarityEl) {
			const hasScore =
				typeof artist.SimilarityScore === 'number' &&
				!Number.isNaN(artist.SimilarityScore);
			if (
				hasScore ||
				(typeof artist.Similarity === 'string' &&
					artist.Similarity.trim().length > 0)
			) {
				const label =
					typeof artist.Similarity === 'string' &&
					artist.Similarity.trim().length > 0
						? artist.Similarity
						: `Similarity: ${(artist.SimilarityScore * 100).toFixed(
								1
						  )}%`;
				similarityEl.textContent = label;
				similarityEl.classList.remove('d-none');
			} else {
				similarityEl.textContent = '';
				similarityEl.classList.add('d-none');
			}
		}
		artist_col.querySelector('.genre').textContent = artist.Genre;
		if (imageContainer) {
			imageContainer.classList.remove('artist-placeholder');
			var existingPlaceholder = imageContainer.querySelector(
				'.artist-placeholder-letter'
			);
			if (existingPlaceholder) {
				existingPlaceholder.remove();
			}
		}
		if (artist.Img_Link && coverImage) {
			coverImage.src = artist.Img_Link;
			coverImage.alt = artist.Name;
			coverImage.classList.remove('d-none');
		} else if (imageContainer) {
			if (coverImage) {
				coverImage.remove();
			}
			imageContainer.classList.add('artist-placeholder');
			var placeholderSpan = document.createElement('span');
			placeholderSpan.className = 'artist-placeholder-letter';
			var firstLetter =
				typeof artist.Name === 'string' && artist.Name.length > 0
					? artist.Name.charAt(0).toUpperCase()
					: '?';
			placeholderSpan.textContent = firstLetter;
			imageContainer.appendChild(placeholderSpan);
		}
		var add_button = artist_col.querySelector('.add-to-lidarr-btn');
		add_button.dataset.defaultText =
			add_button.dataset.defaultText || add_button.textContent;

		// Set button text and handler based on admin status
		if (is_admin) {
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
		artist_col
			.querySelector('.get-preview-btn')
			.addEventListener('click', function () {
				preview_req(artist.Name);
			});
		// Listen to Sample button logic
		artist_col
			.querySelector('.listen-sample-btn')
			.addEventListener('click', function () {
				listenSampleReq(artist.Name);
			});
		artist_col.querySelector('.followers').textContent = artist.Followers;
		artist_col.querySelector('.popularity').textContent = artist.Popularity;

		var statusValue = 'info';

		if (
			artist.Status === 'Added' ||
			artist.Status === 'Already in Lidarr'
		) {
			statusValue = 'success';
			add_button.classList.remove('btn-primary');
			add_button.classList.add('btn-secondary');
			add_button.disabled = true;
			add_button.textContent = artist.Status;
		} else if (artist.Status === 'Requested') {
			statusValue = 'warning';
			add_button.classList.remove('btn-primary');
			add_button.classList.add('btn-warning');
			add_button.disabled = true;
			add_button.textContent = 'Pending Approval';
		} else if (
			artist.Status === 'Failed to Add' ||
			artist.Status === 'Invalid Path' ||
			artist.Status === 'Rejected'
		) {
			statusValue = 'danger';
			add_button.classList.remove('btn-primary');
			add_button.classList.add('btn-danger');
			add_button.disabled = true;
			add_button.textContent = artist.Status;
		} else {
			statusValue = 'info';
		}
		if (statusDot) {
			statusDot.dataset.status = statusValue;
		}
		artist_row.appendChild(clone);
	});
	if (initialLoadComplete) {
		create_load_more_button();
	}
}

// Remove infinite scroll triggers
window.removeEventListener('scroll', function () {});
window.removeEventListener('touchmove', function () {});
window.removeEventListener('touchend', function () {});

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
	var toast_container = document.querySelector('.toast-container');
	var toast_template = document
		.getElementById('toast-template')
		.cloneNode(true);
	toast_template.classList.remove('d-none');

	toast_template.querySelector('.toast-header strong').textContent = header;
	toast_template.querySelector('.toast-body').textContent = message;
	toast_template.querySelector('.text-muted').textContent =
		new Date().toLocaleString();

	toast_container.appendChild(toast_template);

	var toast = new bootstrap.Toast(toast_template);
	toast.show();

	toast_template.addEventListener('hidden.bs.toast', function () {
		toast_template.remove();
	});
}

return_to_top.addEventListener('click', function () {
	window.scrollTo({ top: 0, behavior: 'smooth' });
});

lidarr_select_all_checkbox.addEventListener('change', function () {
	var is_checked = this.checked;
	var checkboxes = document.querySelectorAll('input[name="lidarr-item"]');
	checkboxes.forEach(function (checkbox) {
		checkbox.checked = is_checked;
	});
});

lidarr_get_artists_button.addEventListener('click', function () {
	lidarr_get_artists_button.disabled = true;
	lidarr_spinner.classList.remove('d-none');
	lidarr_status.textContent = 'Accessing Lidarr API';
	lidarr_item_list.innerHTML = '';
	socket.emit('get_lidarr_artists');
});

start_stop_button.addEventListener('click', function () {
	var running_state =
		start_stop_button.textContent.trim() === START_LABEL ? true : false;
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
		var checked_items = Array.from(
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

function build_settings_payload() {
	return {
		lidarr_address: lidarr_address ? lidarr_address.value : '',
		lidarr_api_key: lidarr_api_key ? lidarr_api_key.value : '',
		root_folder_path: root_folder_path ? root_folder_path.value : '',
		youtube_api_key: youtube_api_key ? youtube_api_key.value : '',
		openai_api_key: openai_api_key_input ? openai_api_key_input.value : '',
		openai_api_base: openai_api_base_input
			? openai_api_base_input.value
			: '',
		openai_model: openai_model_input ? openai_model_input.value : '',
		openai_extra_headers: openai_extra_headers_input
			? openai_extra_headers_input.value
			: '',
		openai_max_seed_artists: openai_max_seed_artists_input
			? openai_max_seed_artists_input.value
			: '',
		similar_artist_batch_size: similar_artist_batch_size_input
			? similar_artist_batch_size_input.value
			: '',
		quality_profile_id: quality_profile_id_input
			? quality_profile_id_input.value
			: '',
		metadata_profile_id: metadata_profile_id_input
			? metadata_profile_id_input.value
			: '',
		lidarr_api_timeout: lidarr_api_timeout_input
			? lidarr_api_timeout_input.value
			: '',
		fallback_to_top_result: fallback_to_top_result_checkbox
			? fallback_to_top_result_checkbox.checked
			: false,
		search_for_missing_albums: search_for_missing_albums_checkbox
			? search_for_missing_albums_checkbox.checked
			: false,
		dry_run_adding_to_lidarr: dry_run_adding_to_lidarr_checkbox
			? dry_run_adding_to_lidarr_checkbox.checked
			: false,
		lidarr_monitor_option: lidarr_monitor_option_select
			? lidarr_monitor_option_select.value
			: '',
		lidarr_monitor_new_items: lidarr_monitor_new_items_select
			? lidarr_monitor_new_items_select.value
			: '',
		lidarr_monitored: lidarr_monitored_checkbox
			? lidarr_monitored_checkbox.checked
			: true,
		lidarr_albums_to_monitor: lidarr_albums_to_monitor_input
			? lidarr_albums_to_monitor_input.value
			: '',
		auto_start: auto_start_checkbox ? auto_start_checkbox.checked : false,
		auto_start_delay: auto_start_delay_input
			? auto_start_delay_input.value
			: '',
		last_fm_api_key: last_fm_api_key_input
			? last_fm_api_key_input.value
			: '',
		last_fm_api_secret: last_fm_api_secret_input
			? last_fm_api_secret_input.value
			: '',
		api_key: api_key_input ? api_key_input.value : '',
	};
}

function populate_settings_form(settings) {
	if (!settings) {
		return;
	}
	if (lidarr_address) {
		lidarr_address.value = settings.lidarr_address || '';
	}
	if (lidarr_api_key) {
		lidarr_api_key.value = settings.lidarr_api_key || '';
	}
	if (root_folder_path) {
		root_folder_path.value = settings.root_folder_path || '';
	}
	if (youtube_api_key) {
		youtube_api_key.value = settings.youtube_api_key || '';
	}
	if (quality_profile_id_input) {
		const qualityProfile = settings.quality_profile_id;
		quality_profile_id_input.value =
			qualityProfile === undefined || qualityProfile === null
				? ''
				: qualityProfile;
	}
	if (metadata_profile_id_input) {
		const metadataProfile = settings.metadata_profile_id;
		metadata_profile_id_input.value =
			metadataProfile === undefined || metadataProfile === null
				? ''
				: metadataProfile;
	}
	if (lidarr_api_timeout_input) {
		const apiTimeout = settings.lidarr_api_timeout;
		lidarr_api_timeout_input.value =
			apiTimeout === undefined || apiTimeout === null ? '' : apiTimeout;
	}
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
	if (lidarr_monitor_option_select) {
		lidarr_monitor_option_select.value =
			settings.lidarr_monitor_option || '';
	}
	if (lidarr_monitor_new_items_select) {
		lidarr_monitor_new_items_select.value =
			settings.lidarr_monitor_new_items || '';
	}
	if (lidarr_monitored_checkbox) {
		if (typeof settings.lidarr_monitored === 'boolean') {
			lidarr_monitored_checkbox.checked = settings.lidarr_monitored;
		} else {
			lidarr_monitored_checkbox.checked = true;
		}
	}
	if (lidarr_albums_to_monitor_input) {
		lidarr_albums_to_monitor_input.value =
			settings.lidarr_albums_to_monitor || '';
	}
	if (similar_artist_batch_size_input) {
		const batchSize = settings.similar_artist_batch_size;
		similar_artist_batch_size_input.value =
			batchSize === undefined || batchSize === null ? '' : batchSize;
	}
	if (auto_start_checkbox) {
		auto_start_checkbox.checked = Boolean(settings.auto_start);
	}
	if (auto_start_delay_input) {
		const autoStartDelay = settings.auto_start_delay;
		auto_start_delay_input.value =
			autoStartDelay === undefined || autoStartDelay === null
				? ''
				: autoStartDelay;
	}
	if (last_fm_api_key_input) {
		last_fm_api_key_input.value = settings.last_fm_api_key || '';
	}
	if (last_fm_api_secret_input) {
		last_fm_api_secret_input.value = settings.last_fm_api_secret || '';
	}
	if (api_key_input) {
		api_key_input.value = settings.api_key || '';
	}
	if (openai_api_key_input) {
		openai_api_key_input.value = settings.openai_api_key || '';
	}
	if (openai_api_base_input) {
		openai_api_base_input.value = settings.openai_api_base || '';
	}
	if (openai_model_input) {
		openai_model_input.value = settings.openai_model || '';
	}
	if (openai_extra_headers_input) {
		openai_extra_headers_input.value = settings.openai_extra_headers || '';
	}
	if (openai_max_seed_artists_input) {
		const maxSeedArtists = settings.openai_max_seed_artists;
		openai_max_seed_artists_input.value =
			maxSeedArtists === undefined || maxSeedArtists === null
				? ''
				: maxSeedArtists;
	}
}

function handle_settings_saved(payload) {
	if (save_changes_button) {
		save_changes_button.disabled = false;
	}
	if (save_message) {
		save_message.classList.remove('alert-danger');
		if (!save_message.classList.contains('alert-success')) {
			save_message.classList.add('alert-success');
		}
		save_message.classList.remove('d-none');
		save_message.textContent =
			(payload && payload.message) || 'Settings saved successfully.';
	}
	show_toast(
		'Settings saved',
		(payload && payload.message) || 'Configuration updated successfully.'
	);
}

function handle_settings_save_error(payload) {
	if (save_changes_button) {
		save_changes_button.disabled = false;
	}
	const message =
		(payload && payload.message) ||
		'Saving settings failed. Check the logs for more details.';
	if (save_message) {
		save_message.classList.remove('d-none');
		save_message.classList.remove('alert-success');
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

lidarr_sidebar.addEventListener('show.bs.offcanvas', function (event) {
	socket.emit('side_bar_opened');
	socket.emit('personal_sources_poll');
});

socket.on('lidarr_sidebar_update', (response) => {
	if (response.Status == 'Success') {
		lidarr_status.textContent = 'Lidarr List Retrieved';
		lidarr_items = response.Data;
		lidarr_item_list.innerHTML = '';
		lidarr_select_all_container.classList.remove('d-none');

		for (var i = 0; i < lidarr_items.length; i++) {
			var item = lidarr_items[i];

			var div = document.createElement('div');
			div.className = 'form-check';

			var input = document.createElement('input');
			input.type = 'checkbox';
			input.className = 'form-check-input';
			input.id = 'lidarr-' + i;
			input.name = 'lidarr-item';
			input.value = item.name;

			if (item.checked) {
				input.checked = true;
			}

			var label = document.createElement('label');
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
	var artist_cards = document.querySelectorAll('#artist-column');
	artist_cards.forEach(function (card) {
		var cardEl = card.querySelector('.artist-card');
		if (!cardEl) {
			return;
		}
		var titleEl = cardEl.querySelector('.card-title');
		var card_artist_name = titleEl ? titleEl.textContent.trim() : '';

		if (card_artist_name === artist.Name) {
			var add_button = cardEl.querySelector('.add-to-lidarr-btn');
			var statusDot = cardEl.querySelector('.led');
			var statusValue = 'info';

			if (
				artist.Status === 'Added' ||
				artist.Status === 'Already in Lidarr'
			) {
				statusValue = 'success';
				add_button.classList.remove('btn-primary');
				add_button.classList.add('btn-secondary');
				add_button.disabled = true;
				add_button.innerHTML = artist.Status;
				add_button.dataset.loading = '';
			} else if (artist.Status === 'Requested') {
				statusValue = 'warning';
				add_button.classList.remove('btn-primary');
				add_button.classList.add('btn-warning');
				add_button.disabled = true;
				add_button.innerHTML = 'Pending Approval';
				add_button.dataset.loading = '';
			} else if (
				artist.Status === 'Failed to Add' ||
				artist.Status === 'Invalid Path' ||
				artist.Status === 'Rejected'
			) {
				statusValue = 'danger';
				add_button.classList.remove('btn-primary');
				add_button.classList.add('btn-danger');
				add_button.disabled = true;
				add_button.innerHTML = artist.Status;
				add_button.dataset.loading = '';
			} else {
				statusValue = 'info';
				add_button.disabled = false;
				add_button.classList.remove('btn-danger', 'btn-secondary');
				if (!add_button.classList.contains('btn-primary')) {
					add_button.classList.add('btn-primary');
				}
				add_button.innerHTML =
					add_button.dataset.defaultText || 'Add to Lidarr';
				add_button.dataset.loading = '';
			}
			if (statusDot) {
				statusDot.dataset.status = statusValue;
			}
			return;
		}
	});
});

socket.on('more_artists_loaded', function (data) {
	append_artists(data);
});

socket.on('ai_prompt_ack', function (payload) {
	set_ai_form_loading(false);
	if (payload && Array.isArray(payload.seeds) && payload.seeds.length > 0) {
		var listItems = payload.seeds
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
	var message =
		payload && payload.message
			? payload.message
			: 'We could not complete the AI request right now.';
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
	var source =
		payload && payload.source ? String(payload.source).toLowerCase() : '';
	var username = payload && payload.username ? payload.username : '';
	var seeds = payload && Array.isArray(payload.seeds) ? payload.seeds : [];
	var title = getPersonalServiceTitle(source);
	var message = '';
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
	var source =
		payload && payload.source ? String(payload.source).toLowerCase() : '';
	var message =
		payload && payload.message
			? payload.message
			: 'We could not fetch your personal recommendations right now.';
	hide_header_spinner();
	setPersonalDiscoveryLoading(null, false);
	var title = getPersonalServiceTitle(source);
	show_toast(title, message);
});

// Server signals that initial batches are complete: show the Load More button now
socket.on('initial_load_complete', function (payload) {
	initialLoadComplete = true;
	initialLoadHasMore = !!(payload && payload.hasMore);
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
	initialLoadHasMore = !!(payload && payload.hasMore);
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
	var artist_row = document.getElementById('artist-row');
	var artist_cards = artist_row.querySelectorAll('#artist-column');
	artist_cards.forEach(function (card) {
		card.remove();
	});
	remove_load_more_button();
	initialLoadComplete = false;
	initialLoadHasMore = false;
	loadMorePending = false;
	// spinner state is controlled by the caller
}

var preview_request_flag = false;

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
	var modal_body = document.getElementById('modal-body');
	var modal_title = document.getElementById('bio-modal-title');
	var modalEl = document.getElementById('bio-modal-modal');

	if (typeof preview_info === 'string') {
		if (modal_body) {
			var safeMessage = escape_html(preview_info);
			modal_body.innerHTML = `<div class="alert alert-warning mb-0">${safeMessage}</div>`;
		}
		show_toast('Error Retrieving Bio', preview_info);
		if (modalEl && !modalEl.classList.contains('show')) {
			show_modal_with_lock('bio-modal-modal');
		}
		return;
	}

	var artist_name = preview_info.artist_name;
	var biography = preview_info.biography;
	if (modal_title) {
		modal_title.textContent = artist_name;
	}
	if (modal_body) {
		var biographyHtml = render_biography_html(biography);
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
	if (data && (data.videoId || data.previewUrl)) {
		update_audio_modal_content(data);
	} else {
		var message =
			data && data.error
				? data.error
				: 'No YouTube or audio preview found.';
		show_audio_modal_error(message);
		show_toast('No sample found', message);
	}
});
