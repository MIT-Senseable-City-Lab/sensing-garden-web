/**
 * Unified Device Feed System
 * Handles fetching, merging, and displaying content from multiple endpoints
 * Features: LRU cache with TTL, parallel fetching, smart pagination, real-time filtering
 */

/**
 * LRU Cache with TTL (Time To Live) support
 * Provides fast access to recently used data with automatic expiration
 */
class LRUCache {
    constructor(maxSize = 100, ttlMinutes = 5) {
        this.maxSize = maxSize;
        this.ttlMs = ttlMinutes * 60 * 1000;
        this.cache = new Map();
        this.accessOrder = new Map(); // Track access order for LRU
    }
    
    set(key, value) {
        const now = Date.now();
        const entry = {
            value: value,
            timestamp: now,
            lastAccessed: now
        };
        
        // Remove existing entry if it exists
        if (this.cache.has(key)) {
            this.cache.delete(key);
            this.accessOrder.delete(key);
        }
        
        // Add new entry
        this.cache.set(key, entry);
        this.accessOrder.set(key, now);
        
        // Evict if over capacity
        this._evictIfNeeded();
        
        console.log(`[LRUCache] Set key: ${key}, cache size: ${this.cache.size}`);
    }
    
    get(key) {
        const entry = this.cache.get(key);
        if (!entry) {
            return null;
        }
        
        const now = Date.now();
        
        // Check if expired
        if (now - entry.timestamp > this.ttlMs) {
            console.log(`[LRUCache] Key expired: ${key}`);
            this.cache.delete(key);
            this.accessOrder.delete(key);
            return null;
        }
        
        // Update access time for LRU
        entry.lastAccessed = now;
        this.accessOrder.set(key, now);
        
        console.log(`[LRUCache] Cache hit: ${key}`);
        return entry.value;
    }
    
    has(key) {
        return this.get(key) !== null;
    }
    
    clear() {
        this.cache.clear();
        this.accessOrder.clear();
        console.log('[LRUCache] Cache cleared');
    }
    
    _evictIfNeeded() {
        const now = Date.now();
        
        // First, remove expired entries
        for (const [key, entry] of this.cache.entries()) {
            if (now - entry.timestamp > this.ttlMs) {
                this.cache.delete(key);
                this.accessOrder.delete(key);
            }
        }
        
        // Then, evict least recently used if still over capacity
        while (this.cache.size > this.maxSize) {
            const oldestKey = this._findLeastRecentlyUsed();
            if (oldestKey) {
                console.log(`[LRUCache] Evicting LRU key: ${oldestKey}`);
                this.cache.delete(oldestKey);
                this.accessOrder.delete(oldestKey);
            } else {
                break; // Safety break
            }
        }
    }
    
    _findLeastRecentlyUsed() {
        let oldestKey = null;
        let oldestTime = Date.now();
        
        for (const [key, accessTime] of this.accessOrder.entries()) {
            if (accessTime < oldestTime) {
                oldestTime = accessTime;
                oldestKey = key;
            }
        }
        
        return oldestKey;
    }
    
    getStats() {
        const now = Date.now();
        const validEntries = [];
        const expiredCount = [];
        
        for (const [key, entry] of this.cache.entries()) {
            if (now - entry.timestamp > this.ttlMs) {
                expiredCount.push(key);
            } else {
                validEntries.push(key);
            }
        }
        
        return {
            totalSize: this.cache.size,
            validEntries: validEntries.length,
            expiredEntries: expiredCount.length,
            maxSize: this.maxSize,
            ttlMinutes: this.ttlMs / (60 * 1000)
        };
    }
}

/**
 * Utility functions for safe date handling and formatting
 * Provides robust date parsing with fallbacks for invalid timestamps
 */
class DateUtils {
    /**
     * Safely parse a timestamp with multiple format support
     * @param {string|number|Date} timestamp - The timestamp to parse
     * @returns {Date|null} - Valid Date object or null if invalid
     */
    static safeParseDate(timestamp) {
        if (!timestamp) {
            return null;
        }
        
        let date;
        
        try {
            // Handle different timestamp formats
            if (typeof timestamp === 'string') {
                // Handle custom format: "2025-06-04T14-04-10-100268_0238"
                // Convert to ISO format by replacing hyphens in time with colons
                if (timestamp.includes('T') && /T\d{2}-\d{2}-\d{2}/.test(timestamp)) {
                    // Extract the date and time parts
                    const [datePart, timePart] = timestamp.split('T');
                    if (timePart) {
                        // Replace first two hyphens in time part with colons: "14-04-10-100268_0238" -> "14:04:10-100268_0238"
                        const fixedTimePart = timePart.replace(/^(\d{2})-(\d{2})-(\d{2})/, '$1:$2:$3');
                        // Remove the microseconds and suffix: "14:04:10-100268_0238" -> "14:04:10"
                        const cleanTimePart = fixedTimePart.split('-')[0];
                        const fixedTimestamp = `${datePart}T${cleanTimePart}`;
                        date = new Date(fixedTimestamp);
                    } else {
                        date = new Date(timestamp);
                    }
                }
                // Handle ISO strings with Z suffix
                else if (timestamp.endsWith('Z')) {
                    date = new Date(timestamp);
                } 
                // Handle ISO strings without timezone
                else if (timestamp.includes('T')) {
                    date = new Date(timestamp);
                }
                // Handle other string formats
                else {
                    date = new Date(timestamp);
                }
            } else if (typeof timestamp === 'number') {
                // Handle Unix timestamps (both seconds and milliseconds)
                const timestampMs = timestamp < 10000000000 ? timestamp * 1000 : timestamp;
                date = new Date(timestampMs);
            } else if (timestamp instanceof Date) {
                date = timestamp;
            } else {
                return null;
            }
            
            // Check if the date is valid
            if (isNaN(date.getTime())) {
                console.warn('[DateUtils] Invalid date detected:', timestamp);
                return null;
            }
            
            return date;
        } catch (error) {
            console.warn('[DateUtils] Error parsing timestamp:', timestamp, error);
            return null;
        }
    }
    
    /**
     * Safely format a timestamp for display
     * @param {string|number|Date} timestamp - The timestamp to format
     * @param {Object} options - Formatting options
     * @returns {string} - Formatted date string or fallback
     */
    static safeFormatDate(timestamp, options = {}) {
        const {
            fallback = 'Date unavailable',
            locale = undefined,
            formatOptions = {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }
        } = options;
        
        const date = this.safeParseDate(timestamp);
        
        if (!date) {
            return fallback;
        }
        
        try {
            return date.toLocaleString(locale, formatOptions);
        } catch (error) {
            console.warn('[DateUtils] Error formatting date:', timestamp, error);
            // Fallback to simpler formatting
            try {
                return date.toLocaleString();
            } catch (fallbackError) {
                console.warn('[DateUtils] Fallback formatting also failed:', fallbackError);
                return fallback;
            }
        }
    }
    
    /**
     * Get a formatted timestamp for search indexing
     * @param {string|number|Date} timestamp - The timestamp to format
     * @returns {string} - Searchable date string
     */
    static getSearchableTimestamp(timestamp) {
        const date = this.safeParseDate(timestamp);
        if (!date) {
            return '';
        }
        
        try {
            // Return a consistently formatted string for search
            return date.toLocaleString();
        } catch (error) {
            console.warn('[DateUtils] Error creating searchable timestamp:', error);
            return '';
        }
    }
    
    /**
     * Check if a timestamp is valid
     * @param {string|number|Date} timestamp - The timestamp to validate
     * @returns {boolean} - True if valid, false otherwise
     */
    static isValidTimestamp(timestamp) {
        return this.safeParseDate(timestamp) !== null;
    }
    
    /**
     * Get a relative time string (e.g., "2 hours ago")
     * @param {string|number|Date} timestamp - The timestamp
     * @returns {string} - Relative time string or fallback
     */
    static getRelativeTime(timestamp) {
        const date = this.safeParseDate(timestamp);
        if (!date) {
            return 'Unknown time';
        }
        
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffSeconds = Math.floor(diffMs / 1000);
        const diffMinutes = Math.floor(diffSeconds / 60);
        const diffHours = Math.floor(diffMinutes / 60);
        const diffDays = Math.floor(diffHours / 24);
        
        if (diffSeconds < 60) {
            return 'Just now';
        } else if (diffMinutes < 60) {
            return `${diffMinutes} minute${diffMinutes !== 1 ? 's' : ''} ago`;
        } else if (diffHours < 24) {
            return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
        } else if (diffDays < 30) {
            return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
        } else {
            // For older dates, show formatted date
            return this.safeFormatDate(timestamp, {
                formatOptions: {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric'
                }
            });
        }
    }
    
    /**
     * Extract timestamp from an item object, checking multiple possible fields
     * @param {Object} item - The item object to extract timestamp from
     * @returns {string|number|Date|null} - The extracted timestamp or null
     */
    static extractTimestamp(item) {
        if (!item || typeof item !== 'object') {
            return null;
        }
        
        // Check multiple possible timestamp fields in order of preference
        const timestampFields = [
            'timestamp',       // Main timestamp field
            '_timestamp',      // Backend processed timestamp
            'formatted_time',  // Formatted timestamp
            'created_at',      // Creation timestamp
            'recorded_at',     // Recording timestamp
            'detected_at',     // Detection timestamp
            'time',           // Generic time field
            'date'            // Generic date field
        ];
        
        for (const field of timestampFields) {
            if (item[field] !== undefined && item[field] !== null) {
                return item[field];
            }
        }
        
        return null;
    }
}

class UnifiedFeed {
    constructor(deviceId, options = {}) {
        this.deviceId = deviceId;
        this.options = {
            apiBaseUrl: options.apiBaseUrl || '/api',
            apiKey: options.apiKey || '',
            pageSize: options.pageSize || 20,
            cacheSize: options.cacheSize || 200,
            cacheTtlMinutes: options.cacheTtlMinutes || 5,
            retryAttempts: options.retryAttempts || 3,
            retryDelayMs: options.retryDelayMs || 1000,
            ...options
        };
        
        // Initialize cache
        this.cache = new LRUCache(this.options.cacheSize, this.options.cacheTtlMinutes);
        
        // Current filter state
        this.currentFilters = {
            contentType: 'all',
            dateRange: 'all',
            sortOrder: 'desc',
            searchQuery: ''
        };
        
        // Pagination state for each content type
        this.paginationState = {
            classifications: {
                nextToken: null,
                hasMore: true,
                loading: false,
                totalLoaded: 0
            },
            videos: {
                nextToken: null,
                hasMore: true,
                loading: false,
                totalLoaded: 0
            },
            environment: {
                nextToken: null,
                hasMore: true,
                loading: false,
                totalLoaded: 0
            }
        };
        
        // Global loading and state management
        this.isLoading = false;
        this.hasMoreContent = false;
        this.allLoadedItems = [];
        this.displayedItems = [];
        this.errorCount = 0;
        this.lastRefresh = null;
        
        // Performance monitoring
        this.performanceMetrics = {
            fetchTimes: [],
            renderTimes: [],
            cacheHits: 0,
            cacheMisses: 0
        };
        
        // Get UI elements
        this.loadingIndicator = document.getElementById('loadingIndicator');
        this.errorMessage = document.getElementById('errorMessage');
        this.feedTimeline = document.getElementById('feedTimeline');
        this.emptyState = document.getElementById('emptyState');
        this.loadMoreBtn = document.getElementById('loadMoreBtn');
        this.loadMoreContainer = document.getElementById('loadMoreContainer');
        
        // Bind methods to preserve context
        this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
        this.handleOnlineOffline = this.handleOnlineOffline.bind(this);
        
        // Set up event listeners for performance optimization
        this._setupEventListeners();
    }
    
    /**
     * Set up event listeners for performance optimization
     */
    _setupEventListeners() {
        // Handle page visibility changes to pause/resume updates
        if (typeof document.hidden !== "undefined") {
            document.addEventListener("visibilitychange", this.handleVisibilityChange, false);
        }
        
        // Handle online/offline events for better error handling
        window.addEventListener('online', this.handleOnlineOffline);
        window.addEventListener('offline', this.handleOnlineOffline);
        
        // Handle window beforeunload to cleanup
        window.addEventListener('beforeunload', () => {
            this.cleanup();
        });
    }
    
    /**
     * Handle page visibility changes to optimize performance
     */
    handleVisibilityChange() {
        if (document.hidden) {
            console.log('[UnifiedFeed] Page hidden, pausing updates');
        } else {
            console.log('[UnifiedFeed] Page visible, resuming updates');
            // Optionally refresh if data is stale
            if (this.lastRefresh && Date.now() - this.lastRefresh > 5 * 60 * 1000) {
                console.log('[UnifiedFeed] Data is stale, refreshing...');
                this.refresh();
            }
        }
    }
    
    /**
     * Handle online/offline status changes
     */
    handleOnlineOffline() {
        if (navigator.onLine) {
            console.log('[UnifiedFeed] Network is online');
            this.errorCount = 0; // Reset error count when back online
        } else {
            console.log('[UnifiedFeed] Network is offline');
        }
    }
    
    /**
     * Cleanup method to remove event listeners and clear cache
     */
    cleanup() {
        document.removeEventListener("visibilitychange", this.handleVisibilityChange);
        window.removeEventListener('online', this.handleOnlineOffline);
        window.removeEventListener('offline', this.handleOnlineOffline);
        this.cache.clear();
    }
    
    async initialize() {
        try {
            console.log('Initializing unified feed for device:', this.deviceId);
            this.showLoading();
            await this.loadInitialData();
            this.hideLoading();
            this.showFeed();
        } catch (error) {
            console.error('Failed to initialize feed:', error);
            this.showError('Failed to load feed data: ' + error.message);
        }
    }
    
    /**
     * Load initial data with sophisticated caching and parallel fetching
     */
    async loadInitialData() {
        const startTime = Date.now();
        console.log('[UnifiedFeed] Loading initial data...');
        
        // Reset pagination state
        this._resetPaginationState();
        
        // Clear existing items
        this.allLoadedItems = [];
        this.displayedItems = [];
        
        try {
            // Load data with intelligent parallel fetching
            const allItems = await this._fetchAllContentTypes();
            
            // Merge and sort all items
            console.log('[UnifiedFeed] Raw items before merge:', allItems);
            this.allLoadedItems = this._mergeAndSortItems(allItems);
            console.log('[UnifiedFeed] After merge and sort:', this.allLoadedItems);
            
            // Apply current filters and render
            await this._applyFiltersAndRender();
            
            // Update UI state
            this._updateHasMoreState();
            
            // Force button to normal state
            this.isLoading = false;
            this._updateLoadMoreButton();
            this.lastRefresh = Date.now();
            
            // Track performance
            const fetchTime = Date.now() - startTime;
            this.performanceMetrics.fetchTimes.push(fetchTime);
            console.log(`[UnifiedFeed] Initial load completed in ${fetchTime}ms`);
            
        } catch (error) {
            console.error('[UnifiedFeed] Failed to load initial data:', error);
            this.showError('Failed to load feed data: ' + error.message);
            throw error;
        }
    }
    
    /**
     * Reset pagination state for all content types
     */
    _resetPaginationState() {
        Object.keys(this.paginationState).forEach(contentType => {
            this.paginationState[contentType] = {
                nextToken: null,
                hasMore: true,
                loading: false,
                totalLoaded: 0
            };
        });
    }
    
    /**
     * Fetch data from all content types with intelligent parallel processing
     */
    async _fetchAllContentTypes() {
        const contentTypes = this._getContentTypesToFetch();
        console.log(`[UnifiedFeed] Fetching from ${contentTypes.length} endpoints:`, contentTypes);
        
        // Create fetch promises with intelligent retry and caching
        const fetchPromises = contentTypes.map(async (contentType) => {
            try {
                return await this._fetchContentTypeWithRetry(contentType);
            } catch (error) {
                console.warn(`[UnifiedFeed] Failed to fetch ${contentType}:`, error);
                return { contentType, items: [], error };
            }
        });
        
        // Execute all fetches in parallel
        const results = await Promise.allSettled(fetchPromises);
        const allItems = [];
        
        // Process results
        results.forEach((result, index) => {
            const contentType = contentTypes[index];
            
            if (result.status === 'fulfilled' && result.value && !result.value.error) {
                const data = result.value;
                console.log(`[UnifiedFeed] ${contentType} loaded: ${data.items.length} items`);
                
                // Add any missing metadata to each item (backend already adds _contentType)
                const itemsWithMetadata = data.items.map(item => {
                    const extractedTimestamp = DateUtils.extractTimestamp(item);
                    return {
                        ...item,
                        _contentType: item._contentType || contentType, // Use backend value if available
                        _timestamp: DateUtils.safeParseDate(extractedTimestamp),
                        _rawTimestamp: extractedTimestamp, // Keep raw timestamp for debugging
                        _id: this._generateItemId(item, item._contentType || contentType)
                    };
                });
                
                allItems.push(...itemsWithMetadata);
                
                // Update pagination state
                if (this.paginationState[contentType]) {
                    this.paginationState[contentType].nextToken = data.next_token || null;
                    this.paginationState[contentType].hasMore = !!data.next_token;
                    this.paginationState[contentType].totalLoaded = data.items.length;
                }
            } else {
                console.warn(`[UnifiedFeed] ${contentType} fetch failed:`, 
                    result.reason || result.value?.error);
                this.errorCount++;
            }
        });
        
        return allItems;
    }
    
    /**
     * Get list of content types to fetch based on current filters
     */
    _getContentTypesToFetch() {
        const allTypes = ['classifications', 'videos', 'environment'];
        
        if (this.currentFilters.contentType === 'all') {
            return allTypes;
        }
        
        return [this.currentFilters.contentType];
    }
    
    /**
     * Fetch content type data with retry logic and caching
     */
    async _fetchContentTypeWithRetry(contentType) {
        const cacheKey = this._generateCacheKey(contentType);
        
        // Try cache first
        let cachedData = this.cache.get(cacheKey);
        if (cachedData) {
            console.log(`[UnifiedFeed] Cache hit for ${contentType}`);
            this.performanceMetrics.cacheHits++;
            return cachedData;
        }
        
        this.performanceMetrics.cacheMisses++;
        
        // Fetch with retry logic
        let lastError;
        for (let attempt = 0; attempt < this.options.retryAttempts; attempt++) {
            try {
                if (attempt > 0) {
                    const delay = this.options.retryDelayMs * Math.pow(2, attempt - 1);
                    console.log(`[UnifiedFeed] Retrying ${contentType} fetch (attempt ${attempt + 1}) after ${delay}ms...`);
                    await this._delay(delay);
                }
                
                const data = await this._fetchContentTypeData(contentType);
                
                // Cache successful result
                this.cache.set(cacheKey, data);
                
                return data;
                
            } catch (error) {
                lastError = error;
                console.warn(`[UnifiedFeed] Attempt ${attempt + 1} failed for ${contentType}:`, error.message);
                
                // Don't retry on client errors (4xx)
                if (error.status && error.status >= 400 && error.status < 500) {
                    break;
                }
            }
        }
        
        throw lastError || new Error(`Failed to fetch ${contentType} after ${this.options.retryAttempts} attempts`);
    }
    
    /**
     * Fetch content type data from the API
     */
    async _fetchContentTypeData(contentType) {
        const pagination = this.paginationState[contentType];
        const url = `${this.options.apiBaseUrl}/api/device/${this.deviceId}/feed_data`;
        
        const params = new URLSearchParams({
            content_type: contentType,
            limit: this.options.pageSize,
            sort_desc: this.currentFilters.sortOrder === 'desc' ? 'true' : 'false'
        });
        
        // Add pagination token if available
        if (pagination && pagination.nextToken) {
            params.append('next_token', pagination.nextToken);
        }
        
        // Add date range filter if specified
        if (this.currentFilters.dateRange && this.currentFilters.dateRange !== 'all') {
            const dateRange = this._getDateRangeForFilter(this.currentFilters.dateRange);
            if (dateRange.start) {
                params.append('start_date', dateRange.start);
            }
            if (dateRange.end) {
                params.append('end_date', dateRange.end);
            }
        }
        
        const requestUrl = `${url}?${params.toString()}`;
        console.log(`[UnifiedFeed] Fetching ${contentType} from: ${requestUrl}`);
        
        const response = await fetch(requestUrl, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                ...(this.options.apiKey ? { 'Authorization': `Bearer ${this.options.apiKey}` } : {})
            }
        });
        
        if (!response.ok) {
            const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
            error.status = response.status;
            throw error;
        }
        
        const data = await response.json();
        
        // Validate response structure
        if (!data || typeof data !== 'object') {
            throw new Error(`Invalid response format for ${contentType}`);
        }
        
        // Ensure items array exists
        if (!Array.isArray(data.items)) {
            data.items = [];
        }
        
        return data;
    }
    
    /**
     * Generate cache key for a content type request
     */
    _generateCacheKey(contentType) {
        const pagination = this.paginationState[contentType];
        const parts = [
            'feed',
            this.deviceId,
            contentType,
            this.options.pageSize,
            this.currentFilters.sortOrder,
            this.currentFilters.dateRange,
            pagination?.nextToken || 'first'
        ];
        return parts.join(':');
    }
    
    /**
     * Generate unique ID for an item
     */
    _generateItemId(item, contentType) {
        const baseId = item.id || item.timestamp || Date.now();
        return `${contentType}_${baseId}_${item.timestamp}`;
    }
    
    /**
     * Get date range object for a filter value
     */
    _getDateRangeForFilter(dateFilter) {
        const now = new Date();
        const ranges = {
            'today': {
                start: new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString(),
                end: new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).toISOString()
            },
            'week': {
                start: new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString(),
                end: now.toISOString()
            },
            'month': {
                start: new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString(),
                end: now.toISOString()
            }
        };
        
        return ranges[dateFilter] || {};
    }
    
    /**
     * Utility method to add delay for retry logic
     */
    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    
    /**
     * Merge and sort items from all content types with intelligent deduplication
     */
    _mergeAndSortItems(allItems) {
        const startTime = Date.now();
        console.log(`[UnifiedFeed] Merging and sorting ${allItems.length} items...`);
        
        // Remove duplicates based on generated IDs
        const uniqueItems = this._deduplicateItems(allItems);
        console.log(`[UnifiedFeed] After deduplication: ${uniqueItems.length} items`);
        
        // Sort by timestamp with sophisticated secondary sorting
        const sortedItems = this._sortItemsIntelligently(uniqueItems);
        
        const sortTime = Date.now() - startTime;
        console.log(`[UnifiedFeed] Sorting completed in ${sortTime}ms`);
        
        return sortedItems;
    }
    
    /**
     * Remove duplicate items based on content type and timestamp
     */
    _deduplicateItems(items) {
        const seenIds = new Set();
        const uniqueItems = [];
        
        items.forEach(item => {
            if (item._id && !seenIds.has(item._id)) {
                seenIds.add(item._id);
                uniqueItems.push(item);
            }
        });
        
        return uniqueItems;
    }
    
    /**
     * Sort items with intelligent multi-level sorting
     */
    _sortItemsIntelligently(items) {
        return items.sort((a, b) => {
            // Primary sort: timestamp (handle null timestamps)
            const aTime = a._timestamp ? a._timestamp.getTime() : 0;
            const bTime = b._timestamp ? b._timestamp.getTime() : 0;
            const timestampSort = this.currentFilters.sortOrder === 'desc' 
                ? bTime - aTime 
                : aTime - bTime;
            
            if (timestampSort !== 0) {
                return timestampSort;
            }
            
            // Secondary sort: content type priority (classifications > environment > videos)
            const typePriority = { classifications: 3, environment: 2, videos: 1 };
            const typeDiff = (typePriority[b._contentType] || 0) - (typePriority[a._contentType] || 0);
            
            if (typeDiff !== 0) {
                return typeDiff;
            }
            
            // Tertiary sort: item-specific properties
            return this._compareItemsByType(a, b);
        });
    }
    
    /**
     * Compare items by type-specific properties
     */
    _compareItemsByType(a, b) {
        if (a._contentType !== b._contentType) {
            return 0;
        }
        
        switch (a._contentType) {
            case 'classifications':
                // Sort by confidence (higher first)
                const confDiff = (b.confidence || 0) - (a.confidence || 0);
                if (confDiff !== 0) return confDiff;
                
                // Then by species name
                return (a.species || '').localeCompare(b.species || '');
                
            case 'environment':
                // Sort by temperature (for consistent ordering)
                return (b.ambient_temperature || 0) - (a.ambient_temperature || 0);
                
            case 'videos':
                // Sort by duration (longer first)
                const aDuration = this._parseDuration(a.duration);
                const bDuration = this._parseDuration(b.duration);
                return bDuration - aDuration;
                
            default:
                return 0;
        }
    }
    
    /**
     * Parse duration string to seconds for comparison
     */
    _parseDuration(duration) {
        if (!duration || typeof duration !== 'string') {
            return 0;
        }
        
        // Handle formats like "30s", "1m 30s", "1:30", etc.
        const matches = duration.match(/(\d+)([sm])/g);
        if (matches) {
            return matches.reduce((total, match) => {
                const [, value, unit] = match.match(/(\d+)([sm])/);
                const seconds = unit === 'm' ? parseInt(value) * 60 : parseInt(value);
                return total + seconds;
            }, 0);
        }
        
        // Handle MM:SS format
        const timeMatch = duration.match(/(\d+):(\d+)/);
        if (timeMatch) {
            const [, minutes, seconds] = timeMatch;
            return parseInt(minutes) * 60 + parseInt(seconds);
        }
        
        return 0;
    }
    
    shouldFetchContentType(contentType) {
        return this.currentFilters.contentType === 'all' || this.currentFilters.contentType === contentType;
    }
    
    sortItems(items) {
        return items.sort((a, b) => {
            const dateA = DateUtils.safeParseDate(a.timestamp);
            const dateB = DateUtils.safeParseDate(b.timestamp);
            const timeA = dateA ? dateA.getTime() : 0;
            const timeB = dateB ? dateB.getTime() : 0;
            return this.currentFilters.sortOrder === 'desc' ? timeB - timeA : timeA - timeB;
        });
    }
    
    /**
     * Apply current filters to loaded items and render the result
     */
    async _applyFiltersAndRender() {
        const startTime = Date.now();
        console.log('[UnifiedFeed] Applying filters and rendering...');
        
        // Apply filters to get display items
        this.displayedItems = this._applyFiltersToItems(this.allLoadedItems);
        console.log(`[UnifiedFeed] Filtered to ${this.displayedItems.length} items`, this.displayedItems);
        
        // Render the filtered items
        await this._renderTimelineItemsWithPagination(this.displayedItems);
        
        const renderTime = Date.now() - startTime;
        this.performanceMetrics.renderTimes.push(renderTime);
        console.log(`[UnifiedFeed] Rendering completed in ${renderTime}ms`);
    }
    
    /**
     * Apply filters to a list of items
     */
    _applyFiltersToItems(items) {
        let filteredItems = [...items];
        
        // Filter by content type
        if (this.currentFilters.contentType !== 'all') {
            filteredItems = filteredItems.filter(item => 
                item._contentType === this.currentFilters.contentType);
        }
        
        // Filter by date range (client-side filtering for already loaded items)
        if (this.currentFilters.dateRange !== 'all') {
            const dateRange = this._getDateRangeForFilter(this.currentFilters.dateRange);
            if (dateRange.start && dateRange.end) {
                const startDate = new Date(dateRange.start);
                const endDate = new Date(dateRange.end);
                filteredItems = filteredItems.filter(item => {
                    const itemDate = DateUtils.safeParseDate(item.timestamp);
                    if (!itemDate) {
                        return false; // Exclude items with invalid timestamps
                    }
                    return itemDate >= startDate && itemDate <= endDate;
                });
            }
        }
        
        // Filter by search query if provided
        if (this.currentFilters.searchQuery && this.currentFilters.searchQuery.trim()) {
            const query = this.currentFilters.searchQuery.toLowerCase().trim();
            filteredItems = filteredItems.filter(item => 
                this._itemMatchesSearchQuery(item, query));
        }
        
        return filteredItems;
    }
    
    /**
     * Check if an item matches the search query
     */
    _itemMatchesSearchQuery(item, query) {
        const searchFields = [];
        
        switch (item._contentType) {
            case 'classifications':
                searchFields.push(
                    item.species || '',
                    (item.confidence || 0).toString()
                );
                break;
                
            case 'environment':
                searchFields.push(
                    (item.ambient_temperature || '').toString(),
                    (item.ambient_humidity || '').toString(),
                    (item.pm2p5 || '').toString(),
                    (item.voc_index || '').toString()
                );
                break;
                
            case 'videos':
                searchFields.push(
                    item.duration || '',
                    item.resolution || ''
                );
                break;
        }
        
        // Also include timestamp in searchable text
        searchFields.push(DateUtils.getSearchableTimestamp(item.timestamp));
        
        const searchText = searchFields.join(' ').toLowerCase();
        return searchText.includes(query);
    }
    
    /**
     * Update the hasMoreContent flag based on pagination state
     */
    _updateHasMoreState() {
        // Check if any content type has more data to load, considering content type filter
        const relevantStates = Object.entries(this.paginationState)
            .filter(([contentType, state]) => this.shouldFetchContentType(contentType))
            .map(([contentType, state]) => state);
        
        this.hasMoreContent = relevantStates.some(state => state.hasMore);
        
        console.log(`[UnifiedFeed] Has more content: ${this.hasMoreContent}`);
        console.log(`[UnifiedFeed] Relevant pagination states:`, relevantStates.map((state, i) => 
            `${Object.keys(this.paginationState)[i]}: hasMore=${state.hasMore}, nextToken=${!!state.nextToken}`
        ).join(', '));
    }
    
    /**
     * Render timeline items with performance optimization for large lists and time markers
     */
    async _renderTimelineItemsWithPagination(items) {
        const startTime = Date.now();
        
        // Clear existing timeline
        this.feedTimeline.innerHTML = '';
        
        console.log(`[UnifiedFeed] Rendering ${items.length} items to timeline`, items);
        
        if (items.length === 0) {
            console.log('[UnifiedFeed] No items to render, showing empty state');
            this.showEmpty();
            return;
        }
        
        // Generate time markers for the items
        const timeMarkers = this._generateTimeMarkers(items);
        console.log(`[UnifiedFeed] Generated ${timeMarkers.length} time markers`);
        
        // Merge items and time markers for rendering
        const renderableItems = this._mergeItemsWithTimeMarkers(items, timeMarkers);
        console.log(`[UnifiedFeed] Merged into ${renderableItems.length} renderable items`);
        
        // Use requestAnimationFrame for smooth rendering of large lists
        const batchSize = 10;
        let currentIndex = 0;
        
        const renderBatch = () => {
            const endIndex = Math.min(currentIndex + batchSize, renderableItems.length);
            
            for (let i = currentIndex; i < endIndex; i++) {
                const item = renderableItems[i];
                const element = item.isTimeMarker ? 
                    this._createTimeMarkerElement(item) : 
                    this.createTimelineItem(item);
                this.feedTimeline.appendChild(element);
            }
            
            currentIndex = endIndex;
            
            if (currentIndex < renderableItems.length) {
                requestAnimationFrame(renderBatch);
            } else {
                const renderTime = Date.now() - startTime;
                console.log(`[UnifiedFeed] Rendered ${renderableItems.length} items in ${renderTime}ms`);
                this.showFeed();
                // Render bounding box overlays after items are displayed
                this._renderBboxOverlays();
            }
        };
        
        // Start the rendering process
        requestAnimationFrame(renderBatch);
    }
    
    renderTimelineItems(items) {
        this.feedTimeline.innerHTML = '';
        
        if (items.length === 0) {
            this.showEmpty();
            return;
        }
        
        items.forEach(item => {
            const timelineItem = this.createTimelineItem(item);
            this.feedTimeline.appendChild(timelineItem);
        });
        
        this.showFeed();
        // Render bounding box overlays after items are displayed
        this._renderBboxOverlays();
    }
    
    /**
     * Create sophisticated timeline item with enhanced styling and interactivity
     */
    createTimelineItem(item) {
        const div = document.createElement('div');
        div.className = `timeline-item content-${item._contentType}`;
        div.setAttribute('data-item-id', item._id);
        div.setAttribute('data-content-type', item._contentType);
        div.setAttribute('data-timestamp', item.timestamp);
        
        const markerClass = `timeline-marker-${item._contentType}`;
        const timestampToDisplay = DateUtils.extractTimestamp(item) || item.timestamp;
        const timestamp = DateUtils.safeFormatDate(timestampToDisplay);
        const contentHtml = this._generateAdvancedContentHtml(item);
        
        // Add sophisticated animations and interactions
        const animationDelay = Math.random() * 0.1; // Stagger animation timing
        div.style.animationDelay = `${animationDelay}s`;
        div.classList.add('timeline-item-animate');
        
        div.innerHTML = `
            <div class="timeline-marker ${markerClass}">
                <div class="timeline-marker-pulse"></div>
            </div>
            <div class="timeline-content">
                <div class="timeline-header lean">
                    <div class="timeline-header-content">
                        <span class="timeline-title">
                            ${this.getContentTypeIcon(item._contentType)}
                            ${this.getContentTypeTitle(item._contentType)}
                        </span>
                        <span class="timeline-timestamp">
                            ${timestamp}
                        </span>
                    </div>
                    <div class="timeline-actions">
                        ${this._generateActionButtonsHtml(item)}
                    </div>
                </div>
                <div class="timeline-body">
                    ${contentHtml}
                </div>
                <div class="timeline-footer">
                    ${this._generateFooterHtml(item)}
                </div>
            </div>
        `;
        
        // Add event listeners for interactivity
        this._attachItemEventListeners(div, item);
        
        return div;
    }
    
    /**
     * Generate advanced content HTML with sophisticated layouts
     */
    _generateAdvancedContentHtml(item) {
        switch (item._contentType) {
            case 'classifications':
                return this._generateAdvancedClassificationContent(item);
            case 'videos':
                return this._generateAdvancedVideoContent(item);
            case 'environment':
                return this._generateAdvancedEnvironmentContent(item);
            default:
                return '<p class="text-muted">Unknown content type</p>';
        }
    }
    
    /**
     * Generate metadata HTML for timeline header
     */
    _generateMetadataHtml(item) {
        const metadata = [];
        
        switch (item._contentType) {
            case 'classifications':
                if (item.confidence) {
                    const confidence = Math.round(item.confidence * 100);
                    const confidenceClass = confidence > 80 ? 'high' : confidence > 60 ? 'medium' : 'low';
                    metadata.push(`<span class="confidence-badge confidence-${confidenceClass}">${confidence}%</span>`);
                }
                break;
                
            case 'environment':
                if (item.ambient_temperature !== undefined) {
                    metadata.push(`<span class="temp-badge">${item.ambient_temperature.toFixed(1)}°C</span>`);
                }
                break;
                
            case 'videos':
                if (item.duration) {
                    metadata.push(`<span class="duration-badge">${item.duration}</span>`);
                }
                break;
        }
        
        return metadata.join(' ');
    }
    
    /**
     * Generate action buttons HTML
     */
    _generateActionButtonsHtml(item) {
        const actions = [];
        
        // Add view details button
        actions.push(`
            <button class="btn btn-sm btn-outline-secondary action-btn view-details" 
                    title="View Details" data-action="view-details">
                <i class="fas fa-info-circle"></i>
            </button>
        `);
        
        // Add type-specific actions
        switch (item._contentType) {
            case 'classifications':
                if (item.image_url) {
                    actions.push(`
                        <button class="btn btn-sm btn-outline-primary action-btn view-image" 
                                title="View Image" data-action="view-image">
                            <i class="fas fa-image"></i>
                        </button>
                    `);
                }
                break;
                
            case 'videos':
                if (item.video_url) {
                    actions.push(`
                        <button class="btn btn-sm btn-outline-success action-btn download-video" 
                                title="Download Video" data-action="download-video">
                            <i class="fas fa-download"></i>
                        </button>
                    `);
                }
                break;
        }
        
        return actions.join(' ');
    }
    
    /**
     * Generate footer HTML with additional information
     */
    _generateFooterHtml(item) {
        // Footer removed for cleaner timeline interface
        return '';
    }
    
    /**
     * Attach event listeners to timeline item
     */
    _attachItemEventListeners(itemElement, item) {
        // Handle action button clicks
        itemElement.addEventListener('click', (e) => {
            const action = e.target.closest('[data-action]')?.getAttribute('data-action');
            if (action) {
                e.preventDefault();
                e.stopPropagation();
                this._handleItemAction(action, item, itemElement);
            }
        });
        
        // Add hover effects
        itemElement.addEventListener('mouseenter', () => {
            itemElement.classList.add('timeline-item-hover');
        });
        
        itemElement.addEventListener('mouseleave', () => {
            itemElement.classList.remove('timeline-item-hover');
        });
    }
    
    /**
     * Handle item actions
     */
    _handleItemAction(action, item, itemElement) {
        console.log(`[UnifiedFeed] Handling action: ${action} for item:`, item._id);
        
        switch (action) {
            case 'view-details':
                this._showItemDetails(item);
                break;
                
            case 'view-image':
                this._showImageModal(item);
                break;
                
            case 'download-video':
                this._downloadVideo(item);
                break;
                
            default:
                console.warn(`[UnifiedFeed] Unknown action: ${action}`);
        }
    }
    
    /**
     * Generate advanced classification content with sophisticated styling
     */
    _generateAdvancedClassificationContent(item) {
        // Extract all taxonomy and confidence data
        const species = item.species || 'Unknown Species';
        const family = item.family || null;
        const genus = item.genus || null;
        
        // Extract all confidence values
        const speciesConfidence = item.species_confidence ? Math.round(item.species_confidence * 100) : null;
        const familyConfidence = item.family_confidence ? Math.round(item.family_confidence * 100) : null;
        const genusConfidence = item.genus_confidence ? Math.round(item.genus_confidence * 100) : null;
        
        // Use species confidence as primary, fallback to general confidence
        const primaryConfidence = speciesConfidence || (item.confidence ? Math.round(item.confidence * 100) : 0);
        
        // Get confidence styling based on primary confidence
        const confidenceClass = primaryConfidence > 80 ? 'text-success' : primaryConfidence > 60 ? 'text-warning' : 'text-danger';
        const confidenceIcon = primaryConfidence > 80 ? 'fas fa-check-circle' : primaryConfidence > 60 ? 'fas fa-exclamation-triangle' : 'fas fa-times-circle';
        
        let html = `<div class="classification-content compact">`;
        
        if (item.image_url) {
            // Check for bbox data in both 'bbox' and 'bounding_box' fields
            const bboxData = (item.bbox && Array.isArray(item.bbox) && item.bbox.length === 4) ? item.bbox 
                           : (item.bounding_box && Array.isArray(item.bounding_box) && item.bounding_box.length === 4) ? item.bounding_box 
                           : null;
            html += `
                <div class="d-flex align-items-start classification-layout">
                    <div class="classification-image-container flex-shrink-0">
                        <img src="${item.image_url}" 
                             class="timeline-image rounded shadow-sm detection-img clickable-image"
                             onclick="openAdvancedImageModal('${item.image_url}', ${JSON.stringify(bboxData).replace(/"/g, '&quot;')}, '${item.timestamp}', ${JSON.stringify(item).replace(/"/g, '&quot;')})"
                             alt="Classification image"
                             style="width: 80px; height: 80px; object-fit: cover; cursor: pointer;"
                             loading="lazy"
                             data-image-url="${item.image_url}"
                             data-bbox="${bboxData ? JSON.stringify(bboxData).replace(/"/g, '&quot;') : 'null'}"
                             data-timestamp="${item.timestamp}">
                        ${bboxData ? `<svg class="bbox-svg-overlay" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"><polygon points="" style="fill: none; stroke: #ff0000; stroke-width: 2;"></polygon></svg>` : ''}
                    </div>
                    <div class="classification-text-container flex-grow-1">
                        <div class="classification-details">
                            ${this._generateTaxonomyAndConfidenceDisplay(species, family, genus, speciesConfidence, familyConfidence, genusConfidence, item)}
                        </div>
                    </div>
                </div>
            `;
        } else {
            html += `
                <div class="classification-details">
                    ${this._generateTaxonomyAndConfidenceDisplay(species, family, genus, speciesConfidence, familyConfidence, genusConfidence, item)}
                </div>
            `;
        }
        
        html += `</div>`;
        return html;
    }
    
    /**
     * Generate taxonomy and confidence display with all available data
     */
    _generateTaxonomyAndConfidenceDisplay(species, family, genus, speciesConfidence, familyConfidence, genusConfidence, item) {
        let html = `<div class="taxonomy-display mb-2">`;
        
        // Primary species line
        html += `<div class="species-name mb-1"><strong class="text-primary">${species}</strong>`;
        if (speciesConfidence) {
            const confidenceClass = speciesConfidence > 80 ? 'text-success' : speciesConfidence > 60 ? 'text-warning' : 'text-danger';
            html += ` <span class="confidence-badge ${confidenceClass}">${speciesConfidence}%</span>`;
        }
        html += `</div>`;
        
        // Taxonomy hierarchy
        const taxonomyItems = [];
        
        if (family && familyConfidence) {
            taxonomyItems.push(`<span class="taxonomy-item">Family: <strong>${family}</strong> <span class="confidence-small text-muted">${familyConfidence}%</span></span>`);
        }
        
        if (genus && genusConfidence) {
            taxonomyItems.push(`<span class="taxonomy-item">Genus: <strong>${genus}</strong> <span class="confidence-small text-muted">${genusConfidence}%</span></span>`);
        }
        
        if (taxonomyItems.length > 0) {
            html += `<div class="taxonomy-hierarchy text-sm text-muted mb-1">${taxonomyItems.join(' • ')}</div>`;
        }
        
        html += `</div>`;
        
        // Add additional fields
        html += `<div class="classification-metrics">${this._generateAdditionalClassificationFields(item)}</div>`;
        
        return html;
    }
    
    /**
     * Generate additional classification fields for display
     */
    _generateAdditionalClassificationFields(item) {
        const fields = [];
        
        // Detection time
        if (item.detection_time !== undefined && item.detection_time !== null) {
            fields.push(`
                <div class="classification-field">
                    <i class="fas fa-stopwatch text-info me-1" style="font-size: 0.7em;"></i>
                    <small class="text-muted">${item.detection_time}ms detection</small>
                </div>
            `);
        }
        
        // Model version
        if (item.model_version) {
            fields.push(`
                <div class="classification-field">
                    <i class="fas fa-robot text-info me-1" style="font-size: 0.7em;"></i>
                    <small class="text-muted">Model v${item.model_version}</small>
                </div>
            `);
        }
        
        // Bounding box info
        const bboxForDisplay = (item.bbox && Array.isArray(item.bbox) && item.bbox.length === 4) ? item.bbox 
                             : (item.bounding_box && Array.isArray(item.bounding_box) && item.bounding_box.length === 4) ? item.bounding_box 
                             : null;
        if (bboxForDisplay) {
            const [x, y, width, height] = bboxForDisplay;
            fields.push(`
                <div class="classification-field">
                    <i class="fas fa-crop-alt text-info me-1" style="font-size: 0.7em;"></i>
                    <small class="text-muted">Box: ${Math.round(x * 1000) / 1000},${Math.round(y * 1000) / 1000} (${Math.round(width * 1000) / 1000}×${Math.round(height * 1000) / 1000})</small>
                </div>
            `);
        }
        
        // Classification ID (if available)
        if (item.id) {
            fields.push(`
                <div class="classification-field">
                    <i class="fas fa-hashtag text-info me-1" style="font-size: 0.7em;"></i>
                    <small class="text-muted">ID: ${item.id.substring(0, 8)}...</small>
                </div>
            `);
        }
        
        // Additional custom fields from the classification data
        if (item.classification_data && typeof item.classification_data === 'object') {
            for (const [key, value] of Object.entries(item.classification_data)) {
                if (key !== 'name' && key !== 'confidence' && value !== undefined && value !== null) {
                    // Format field name (convert snake_case to readable)
                    const fieldName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                    fields.push(`
                        <div class="classification-field">
                            <i class="fas fa-info-circle text-info me-1" style="font-size: 0.7em;"></i>
                            <small class="text-muted">${fieldName}: ${value}</small>
                        </div>
                    `);
                }
            }
        }
        
        return fields.join('');
    }
    
    /**
     * Generate minimal video content
     */
    _generateAdvancedVideoContent(item) {
        if (item.video_url) {
            return `
                <div class="video-content compact">
                    <video controls 
                           preload="metadata" 
                           class="video-player w-100 rounded">
                        <source src="${item.video_url}" type="video/mp4">
                        Your browser does not support the video tag.
                    </video>
                </div>
            `;
        }
        
        return `<div class="video-content compact"><p class="text-muted">Video not available</p></div>`;
    }
    
    /**
     * Generate advanced environment content with sophisticated visualizations
     */
    _generateAdvancedEnvironmentContent(item) {
        const metrics = [
            { label: 'Temperature', value: item.ambient_temperature, unit: '°C' },
            { label: 'Humidity', value: item.ambient_humidity, unit: '%' },
            { label: 'PM1.0', value: item.pm1p0, unit: 'μg/m³' },
            { label: 'PM2.5', value: item.pm2p5, unit: 'μg/m³' },
            { label: 'PM4.0', value: item.pm4p0, unit: 'μg/m³' },
            { label: 'PM10.0', value: item.pm10p0, unit: 'μg/m³' },
            { label: 'VOC Index', value: item.voc_index, unit: '' },
            { label: 'NOx Index', value: item.nox_index, unit: '' }
        ];
        
        const validMetrics = metrics.filter(m => m.value !== undefined && m.value !== null);
        
        let html = `<div class="environment-content compact">`;
        
        validMetrics.forEach(metric => {
            const value = typeof metric.value === 'number' ? metric.value.toFixed(1) : metric.value;
            html += `<span class="env-metric">${metric.label}: ${value}${metric.unit}</span>`;
        });
        
        html += `</div>`;
        return html;
    }
    
    /**
     * Modal integration methods
     */
    _showImageModal(item) {
        console.log('[UnifiedFeed] Opening image modal for classification:', item._id);
        
        if (typeof showModalWithImageAndBbox === 'function') {
            // Parse bbox if it exists
            const bbox = item.bbox && Array.isArray(item.bbox) ? item.bbox : null;
            showModalWithImageAndBbox(item.image_url, bbox, item.timestamp);
        } else {
            // Fallback to window.open if modal function not available
            console.warn('[UnifiedFeed] showModalWithImageAndBbox not available, using fallback');
            window.open(item.image_url, '_blank');
        }
    }
    
    _showItemDetails(item) {
        console.log('[UnifiedFeed] Showing item details:', item._id);
        
        // Create detailed view modal or expand in place
        const detailsHtml = this._generateItemDetailsHtml(item);
        
        // Use Bootstrap modal or custom implementation
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            ${this.getContentTypeIcon(item._contentType)} 
                            ${this.getContentTypeTitle(item._contentType)} Details
                        </h5>
                        <button type="button" class="close" data-dismiss="modal">
                            <span>&times;</span>
                        </button>
                    </div>
                    <div class="modal-body">
                        ${detailsHtml}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        $(modal).modal('show');
        
        // Cleanup when modal is hidden
        $(modal).on('hidden.bs.modal', () => {
            document.body.removeChild(modal);
        });
    }
    
    _downloadVideo(item) {
        if (item.video_url) {
            console.log('[UnifiedFeed] Downloading video:', item.video_url);
            
            // Use fetch to download the video and force download
            const filename = `sensing-garden-video-${item.timestamp}.mp4`;
            
            fetch(item.video_url)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.blob();
                })
                .then(blob => {
                    // Create object URL for the blob
                    const objectUrl = URL.createObjectURL(blob);
                    
                    // Create and trigger download link
                    const link = document.createElement('a');
                    link.href = objectUrl;
                    link.download = filename;
                    link.style.display = 'none';
                    
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    
                    // Clean up object URL after a delay to ensure download starts
                    setTimeout(() => {
                        URL.revokeObjectURL(objectUrl);
                    }, 1000);
                    
                    console.log('[UnifiedFeed] Video download initiated:', filename);
                })
                .catch(error => {
                    console.error('[UnifiedFeed] Failed to download video:', error);
                    
                    // Fallback: try direct link method
                    console.log('[UnifiedFeed] Attempting fallback download method...');
                    const link = document.createElement('a');
                    link.href = item.video_url;
                    link.download = filename;
                    link.target = '_blank';
                    link.rel = 'noopener';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    
                    // Show user message about fallback
                    alert('Download may open in a new tab. Please save the video from your browser.');
                });
        }
    }
    
    generateContentHtml(item) {
        switch (item._contentType) {
            case 'classifications':
                return this.generateClassificationContent(item);
            case 'videos':
                return this.generateVideoContent(item);
            case 'environment':
                return this.generateEnvironmentContent(item);
            default:
                return '<p>Unknown content type</p>';
        }
    }
    
    generateClassificationContent(item) {
        const confidence = item.confidence ? Math.round(item.confidence * 100) : 0;
        const species = item.species || 'Unknown';
        
        let html = `
            <div class="row">
                <div class="col-md-4">
        `;
        
        if (item.image_url) {
            html += `
                    <img src="${item.image_url}" 
                         class="timeline-image img-fluid"
                         onclick="openImageModal('${item.image_url}', '${item.timestamp}')"
                         alt="Classification image">
            `;
        }
        
        html += `
                </div>
                <div class="col-md-8">
                    <div class="species-info">
                        <p><strong>Species:</strong> ${species}</p>
                        <p><strong>Confidence:</strong> ${confidence}%</p>
                        <div class="progress mb-2">
                            <div class="progress-bar" 
                                 style="width: ${confidence}%"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        return html;
    }
    
    generateVideoContent(item) {
        let html = `
            <div class="row">
                <div class="col-md-6">
        `;
        
        if (item.video_url) {
            html += `
                    <video controls preload="metadata" class="img-fluid">
                        <source src="${item.video_url}" type="video/mp4">
                        Your browser does not support the video tag.
                    </video>
            `;
        }
        
        html += `
                </div>
                <div class="col-md-6">
                    <div class="video-info">
                        <p><strong>Duration:</strong> ${item.duration || 'Unknown'}</p>
                        <p><strong>Resolution:</strong> ${item.resolution || 'Unknown'}</p>
                    </div>
                </div>
            </div>
        `;
        
        return html;
    }
    
    generateEnvironmentContent(item) {
        const metrics = [
            { label: 'Temperature', value: item.ambient_temperature, unit: '°C', type: 'temperature' },
            { label: 'Humidity', value: item.ambient_humidity, unit: '%', type: 'humidity' },
            { label: 'PM2.5', value: item.pm2p5, unit: 'μg/m³', type: 'pm' },
            { label: 'PM10', value: item.pm10p0, unit: 'μg/m³', type: 'pm' },
            { label: 'VOC Index', value: item.voc_index, unit: '', type: 'air-quality' },
            { label: 'NOx Index', value: item.nox_index, unit: '', type: 'air-quality' }
        ];
        
        let html = '<div class="env-grid">';
        
        metrics.forEach(metric => {
            if (metric.value !== undefined && metric.value !== null) {
                const value = typeof metric.value === 'number' ? metric.value.toFixed(1) : metric.value;
                html += `
                    <div class="env-metric" data-metric="${metric.type}">
                        <div class="env-metric-value">${value}${metric.unit}</div>
                        <div class="env-metric-label">${metric.label}</div>
                    </div>
                `;
            }
        });
        
        html += '</div>';
        return html;
    }
    
    getContentTypeIcon(type) {
        const icons = {
            classifications: '<i class="fas fa-bug text-success"></i>',
            videos: '<i class="fas fa-video text-primary"></i>',
            environment: '<i class="fas fa-thermometer-half text-info"></i>'
        };
        return icons[type] || '<i class="fas fa-circle"></i>';
    }
    
    getContentTypeTitle(type) {
        const titles = {
            classifications: 'Insect Classification',
            videos: 'Video',
            environment: 'Environmental Reading'
        };
        return titles[type] || 'Unknown Content';
    }
    
    showLoading() {
        this.loadingIndicator.style.display = 'block';
        this.feedTimeline.style.display = 'none';
        this.errorMessage.style.display = 'none';
        this.emptyState.style.display = 'none';
        this.isLoading = true;
    }
    
    hideLoading() {
        this.loadingIndicator.style.display = 'none';
        this.isLoading = false;
    }
    
    showFeed() {
        this.feedTimeline.style.display = 'block';
        this.errorMessage.style.display = 'none';
        this.emptyState.style.display = 'none';
    }
    
    showEmpty() {
        this.feedTimeline.style.display = 'none';
        this.errorMessage.style.display = 'none';
        this.emptyState.style.display = 'block';
    }
    
    showError(message) {
        this.hideLoading();
        this.errorMessage.style.display = 'block';
        this.feedTimeline.style.display = 'none';
        this.emptyState.style.display = 'none';
        document.getElementById('errorText').textContent = message;
    }
    
    
    /**
     * Apply filters with real-time update
     */
    async applyFilters(filters) {
        console.log('[UnifiedFeed] Applying filters:', filters);
        const previousFilters = { ...this.currentFilters };
        this.currentFilters = { ...this.currentFilters, ...filters };
        
        // Check if we need to fetch new data or can filter client-side
        const needsNewData = this._filtersRequireNewData(previousFilters, this.currentFilters);
        
        if (needsNewData) {
            console.log('[UnifiedFeed] Filter changes require new data fetch');
            this.showLoading();
            
            // Clear cache for content type or date range changes
            this.cache.clear();
            
            try {
                await this.loadInitialData();
            } catch (error) {
                console.error('[UnifiedFeed] Failed to apply filters:', error);
                this.showError('Failed to apply filters: ' + error.message);
            }
        } else {
            console.log('[UnifiedFeed] Applying client-side filters');
            // Apply filters to existing data
            await this._applyFiltersAndRender();
        }
    }
    
    /**
     * Check if filter changes require fetching new data
     */
    _filtersRequireNewData(oldFilters, newFilters) {
        return (
            oldFilters.contentType !== newFilters.contentType ||
            oldFilters.dateRange !== newFilters.dateRange ||
            oldFilters.sortOrder !== newFilters.sortOrder
        );
    }
    
    /**
     * Refresh feed data
     */
    async refresh() {
        console.log('[UnifiedFeed] Refreshing feed data...');
        this.cache.clear();
        this.errorCount = 0;
        await this.initialize();
    }
    
    /**
     * Load more content using advanced pagination
     */
    async loadMore() {
        if (this.isLoading) {
            console.log('[UnifiedFeed] Cannot load more - already loading');
            return;
        }
        
        console.log('[UnifiedFeed] Loading more content...');
        this.isLoading = true;
        this._updateLoadMoreButton();
        
        try {
            // Load more data from endpoints that have more content
            const newItems = await this._loadMoreFromEndpoints();
            
            console.log(`[UnifiedFeed] Loaded ${newItems.length} new items`);
            
            if (newItems.length > 0) {
                // Merge new items with existing
                this.allLoadedItems.push(...newItems);
                this.allLoadedItems = this._mergeAndSortItems(this.allLoadedItems);
                
                // Apply filters to new items only and append to timeline
                await this._appendNewItemsToTimeline(newItems);
            } else {
                console.log('[UnifiedFeed] No new items loaded - showing "nothing more to load" message');
                this._showNoMoreContentDialog();
            }
            
            // Always update state after loading attempt
            this._updateHasMoreState();
            this._updateLoadMoreButton();
            
        } catch (error) {
            console.error('[UnifiedFeed] Failed to load more:', error);
            this.showError('Failed to load more content: ' + error.message);
            
            // Ensure state is updated even on error
            this._updateHasMoreState();
        } finally {
            this.isLoading = false;
            this._updateLoadMoreButton();
        }
    }
    
    /**
     * Append new items to timeline without re-rendering existing items
     */
    async _appendNewItemsToTimeline(newItems) {
        const startTime = Date.now();
        console.log(`[UnifiedFeed] Appending ${newItems.length} new items to timeline`);
        
        // Apply filters to new items only
        const filteredNewItems = this._applyFiltersToItems(newItems);
        console.log(`[UnifiedFeed] After filtering: ${filteredNewItems.length} items to append`);
        
        if (filteredNewItems.length === 0) {
            console.log('[UnifiedFeed] No new items to append after filtering');
            return;
        }
        
        // Update displayed items array
        this.displayedItems.push(...filteredNewItems);
        
        // Generate time markers for new items
        const timeMarkers = this._generateTimeMarkers(filteredNewItems);
        console.log(`[UnifiedFeed] Generated ${timeMarkers.length} time markers for new items`);
        
        // Merge new items with time markers
        const sortedNewItems = this._mergeItemsWithTimeMarkers(filteredNewItems, timeMarkers);
        
        // For "Load More" functionality, we should append items at the end
        // since pagination typically loads older content (or newer depending on sort order)
        // The API should return items in the correct order for appending
        
        // Use requestAnimationFrame for smooth rendering
        const batchSize = 5;
        let currentIndex = 0;
        
        const renderBatch = () => {
            const endIndex = Math.min(currentIndex + batchSize, sortedNewItems.length);
            
            for (let i = currentIndex; i < endIndex; i++) {
                const item = sortedNewItems[i];
                const element = item.isTimeMarker ? 
                    this._createTimeMarkerElement(item) : 
                    this.createTimelineItem(item);
                this.feedTimeline.appendChild(element);
            }
            
            currentIndex = endIndex;
            
            if (currentIndex < sortedNewItems.length) {
                requestAnimationFrame(renderBatch);
            } else {
                const renderTime = Date.now() - startTime;
                console.log(`[UnifiedFeed] Appended ${sortedNewItems.length} items in ${renderTime}ms`);
                // Render bounding box overlays for new items
                this._renderBboxOverlays();
            }
        };
        
        // Start the rendering process
        requestAnimationFrame(renderBatch);
    }
    
    /**
     * Load more data from endpoints that have more content
     */
    async _loadMoreFromEndpoints() {
        const endpointsWithMore = Object.entries(this.paginationState)
            .filter(([contentType, state]) => 
                state.hasMore && 
                !state.loading && 
                this.shouldFetchContentType(contentType)
            );
            
        console.log(`[UnifiedFeed] Checking endpoints for more data:`, endpointsWithMore.map(([type]) => type));
            
        if (endpointsWithMore.length === 0) {
            console.log('[UnifiedFeed] No endpoints have more data');
            // Make sure we mark all relevant content types as having no more data
            Object.entries(this.paginationState).forEach(([contentType, state]) => {
                if (this.shouldFetchContentType(contentType) && !state.nextToken) {
                    state.hasMore = false;
                }
            });
            return [];
        }
        
        console.log(`[UnifiedFeed] Loading more from ${endpointsWithMore.length} endpoints`);
        
        const fetchPromises = endpointsWithMore.map(async ([contentType, state]) => {
            try {
                state.loading = true;
                const data = await this._fetchContentTypeWithRetry(contentType);
                
                console.log(`[UnifiedFeed] Loaded ${data.items.length} items from ${contentType}, next_token: ${!!data.next_token}`);
                
                // Update pagination state
                state.nextToken = data.next_token || null;
                state.hasMore = !!data.next_token;
                state.totalLoaded += data.items.length;
                state.loading = false;
                
                // Add metadata to items
                return data.items.map(item => {
                    const extractedTimestamp = DateUtils.extractTimestamp(item);
                    return {
                        ...item,
                        _contentType: contentType,
                        _timestamp: DateUtils.safeParseDate(extractedTimestamp),
                        _rawTimestamp: extractedTimestamp, // Keep raw timestamp for debugging
                        _id: this._generateItemId(item, contentType)
                    };
                });
                
            } catch (error) {
                console.warn(`[UnifiedFeed] Failed to load more ${contentType}:`, error);
                state.loading = false;
                // If there's an error, assume no more data to prevent infinite retries
                state.hasMore = false;
                return [];
            }
        });
        
        const results = await Promise.allSettled(fetchPromises);
        const allNewItems = [];
        
        results.forEach((result, index) => {
            const [contentType] = endpointsWithMore[index];
            if (result.status === 'fulfilled') {
                allNewItems.push(...result.value);
                console.log(`[UnifiedFeed] Successfully loaded ${result.value.length} items from ${contentType}`);
            } else {
                console.error(`[UnifiedFeed] Failed to load from ${contentType}:`, result.reason);
            }
        });
        
        return allNewItems;
    }
    
    /**
     * Update load more button state
     */
    _updateLoadMoreButton() {
        if (!this.loadMoreBtn || !this.loadMoreContainer) return;
        
        console.log(`[UnifiedFeed] Updating Load More button: isLoading=${this.isLoading}`);
        
        // Always show the button
        this.loadMoreContainer.style.display = 'block';
        this.loadMoreBtn.disabled = this.isLoading;
        
        const loadMoreText = document.getElementById('loadMoreText');
        const loadMoreSpinner = document.getElementById('loadMoreSpinner');
        
        if (loadMoreText) {
            loadMoreText.textContent = this.isLoading ? 'Loading...' : 'Load More';
            loadMoreText.style.display = 'inline-block';
        }
        
        if (loadMoreSpinner) {
            loadMoreSpinner.style.display = this.isLoading ? 'inline-block' : 'none';
        }
    }
    
    /**
     * Show temporary dialog when no more content is available
     */
    _showNoMoreContentDialog() {
        // Create a temporary toast/alert
        const alert = document.createElement('div');
        alert.className = 'alert alert-info alert-dismissible fade show position-fixed';
        alert.style.cssText = 'top: 20px; right: 20px; z-index: 1050; max-width: 300px;';
        alert.innerHTML = `
            <i class="fas fa-info-circle me-2"></i>
            No more content to load
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(alert);
        
        // Auto-remove after 3 seconds
        setTimeout(() => {
            if (alert && alert.parentNode) {
                alert.remove();
            }
        }, 3000);
        
        console.log('[UnifiedFeed] Showed "no more content" dialog');
    }
    
    /**
     * Utility methods for styling and content generation
     */
    _getConfidenceColor(confidence) {
        if (confidence >= 80) return 'bg-success';
        if (confidence >= 60) return 'bg-warning';
        return 'bg-danger';
    }
    
    _getConfidenceDescription(confidence) {
        if (confidence >= 90) return 'Very high confidence';
        if (confidence >= 80) return 'High confidence';
        if (confidence >= 60) return 'Moderate confidence';
        if (confidence >= 40) return 'Low confidence';
        return 'Very low confidence';
    }
    
    _getTemperatureColor(temp) {
        if (temp === undefined || temp === null) return 'text-muted';
        if (temp < 10) return 'text-primary';
        if (temp < 25) return 'text-success';
        if (temp < 35) return 'text-warning';
        return 'text-danger';
    }
    
    _getPMColor(value) {
        if (value === undefined || value === null) return 'text-muted';
        if (value < 12) return 'text-success';
        if (value < 35) return 'text-warning';
        return 'text-danger';
    }
    
    _getVOCColor(value) {
        if (value === undefined || value === null) return 'text-muted';
        if (value < 150) return 'text-success';
        if (value < 250) return 'text-warning';
        return 'text-danger';
    }
    
    _getNOxColor(value) {
        if (value === undefined || value === null) return 'text-muted';
        if (value < 100) return 'text-success';
        if (value < 200) return 'text-warning';
        return 'text-danger';
    }
    
    _getEnvironmentQualityClass(key, value) {
        // Return CSS class based on metric quality
        if (value === undefined || value === null) return 'quality-unknown';
        
        switch (key) {
            case 'pm2p5':
            case 'pm10p0':
                if (value < 12) return 'quality-good';
                if (value < 35) return 'quality-moderate';
                return 'quality-poor';
                
            case 'voc_index':
                if (value < 150) return 'quality-good';
                if (value < 250) return 'quality-moderate';
                return 'quality-poor';
                
            default:
                return 'quality-good';
        }
    }
    
    _getEnvironmentQualityLabel(key, value) {
        const qualityClass = this._getEnvironmentQualityClass(key, value);
        switch (qualityClass) {
            case 'quality-good': return '<span class="badge badge-success">Good</span>';
            case 'quality-moderate': return '<span class="badge badge-warning">Moderate</span>';
            case 'quality-poor': return '<span class="badge badge-danger">Poor</span>';
            default: return '<span class="badge badge-secondary">Unknown</span>';
        }
    }
    
    _generateAirQualitySummary(item) {
        const pm25 = item.pm2p5;
        const pm10 = item.pm10p0;
        const voc = item.voc_index;
        
        if (pm25 !== undefined && pm25 < 12) {
            return "Air quality is good with low particulate matter levels.";
        } else if (pm25 !== undefined && pm25 < 35) {
            return "Air quality is moderate. Sensitive individuals should consider limiting outdoor activities.";
        } else if (pm25 !== undefined) {
            return "Air quality is poor. Consider limiting outdoor activities.";
        }
        
        return "Air quality data is being collected...";
    }
    
    _formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
    
    _generateClassificationMetrics(item) {
        // Additional metrics for classifications
        const metrics = [];
        
        if (item.detection_time) {
            metrics.push(`<small class="text-muted">Detection time: ${item.detection_time}ms</small>`);
        }
        
        if (item.model_version) {
            metrics.push(`<small class="text-muted">Model: v${item.model_version}</small>`);
        }
        
        return metrics.length > 0 ? `<div class="mt-2">${metrics.join('<br>')}</div>` : '';
    }
    
    _generateItemDetailsHtml(item) {
        // Generate detailed HTML for item details modal
        return `
            <div class="item-details">
                <div class="detail-section">
                    <h6>Raw Data</h6>
                    <pre class="bg-light p-3 rounded"><code>${JSON.stringify(item, null, 2)}</code></pre>
                </div>
            </div>
        `;
    }
    
    /**
     * Render bounding box overlays for classification images
     */
    _renderBboxOverlays() {
        console.log('[UnifiedFeed] Calling renderBboxOverlays for timeline images');
        // Call the global renderBboxOverlays function from bbox_overlays.js
        if (typeof renderBboxOverlays === 'function') {
            // Use a small delay to ensure images are fully rendered in the DOM
            setTimeout(() => {
                renderBboxOverlays();
            }, 100);
        } else {
            console.warn('[UnifiedFeed] renderBboxOverlays function not available');
        }
    }

    /**
     * Generate time markers for timeline items
     * Creates major markers (days) and minor markers (hours) with granular hour detection
     * Shows hour markers between any consecutive items that have different hours
     */
    _generateTimeMarkers(items) {
        if (items.length === 0) return [];
        
        const markers = [];
        const seenDays = new Set();
        
        // Sort items by timestamp to ensure proper chronological order
        const sortedItems = [...items].sort((a, b) => {
            const aTime = a._timestamp ? a._timestamp.getTime() : 0;
            const bTime = b._timestamp ? b._timestamp.getTime() : 0;
            return this.currentFilters.sortOrder === 'desc' ? bTime - aTime : aTime - bTime;
        });
        
        sortedItems.forEach((item, index) => {
            if (!item._timestamp) return;
            
            const itemDate = item._timestamp;
            const dayKey = itemDate.toDateString();
            
            // Check if we need a day marker
            if (!seenDays.has(dayKey)) {
                seenDays.add(dayKey);
                markers.push({
                    isTimeMarker: true,
                    type: 'day',
                    timestamp: itemDate,
                    label: itemDate.toLocaleDateString('en-US', {
                        weekday: 'short',
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric'
                    }),
                    sortKey: itemDate.getTime(),
                    itemIndex: index
                });
            }
            
            // Check for hour marker between consecutive items
            if (index > 0) {
                const prevItem = sortedItems[index - 1];
                if (prevItem._timestamp) {
                    const prevDate = prevItem._timestamp;
                    const prevDayKey = prevDate.toDateString();
                    const currentHour = itemDate.getHours();
                    const prevHour = prevDate.getHours();
                    
                    // Add hour marker if hours are different (crossing hour boundary)
                    if (currentHour !== prevHour) {
                        // Don't add hour marker if we're on a different day (day markers already provide time context)
                        const isDifferentDay = dayKey !== prevDayKey;
                        
                        if (!isDifferentDay) {
                            // Create hour marker for the current item's hour
                            const hourMarkerTime = new Date(itemDate);
                            hourMarkerTime.setMinutes(0, 0, 0); // Round to the top of the hour
                            
                            markers.push({
                                isTimeMarker: true,
                                type: 'hour',
                                timestamp: hourMarkerTime,
                                label: hourMarkerTime.toLocaleTimeString('en-US', {
                                    hour: 'numeric',
                                    minute: '2-digit',
                                    hour12: true
                                }),
                                sortKey: itemDate.getTime() - 1, // Ensure hour marker appears just before the item
                                itemIndex: index
                            });
                        }
                    }
                }
            }
        });
        
        return markers;
    }
    
    /**
     * Merge timeline items with time markers in chronological order
     */
    _mergeItemsWithTimeMarkers(items, markers) {
        const allItems = [...items, ...markers];
        
        // Sort all items by timestamp
        return allItems.sort((a, b) => {
            const aTime = a._timestamp ? a._timestamp.getTime() : a.sortKey || 0;
            const bTime = b._timestamp ? b._timestamp.getTime() : b.sortKey || 0;
            
            // If timestamps are equal, time markers should come before timeline items
            if (aTime === bTime) {
                if (a.isTimeMarker && !b.isTimeMarker) return -1;
                if (!a.isTimeMarker && b.isTimeMarker) return 1;
                // If both are time markers, day markers come before hour markers
                if (a.isTimeMarker && b.isTimeMarker) {
                    if (a.type === 'day' && b.type === 'hour') return -1;
                    if (a.type === 'hour' && b.type === 'day') return 1;
                }
            }
            
            return this.currentFilters.sortOrder === 'desc' ? bTime - aTime : aTime - bTime;
        });
    }
    
    /**
     * Create a time marker HTML element
     */
    _createTimeMarkerElement(marker) {
        const div = document.createElement('div');
        div.className = `time-marker time-marker-${marker.type}`;
        div.setAttribute('data-timestamp', marker.timestamp.toISOString());
        div.setAttribute('data-type', marker.type);
        
        const markerClass = marker.type === 'day' ? 'time-marker-major' : 'time-marker-minor';
        const iconClass = marker.type === 'day' ? 'fas fa-calendar-day' : 'fas fa-clock';
        
        div.innerHTML = `
            <div class="time-marker-line ${markerClass}">
                <div class="time-marker-label">
                    <i class="${iconClass}"></i>
                    <span>${marker.label}</span>
                </div>
            </div>
        `;
        
        return div;
    }
    
    /**
     * Performance monitoring and debugging
     */
    getPerformanceStats() {
        const stats = this.cache.getStats();
        return {
            cache: stats,
            performance: {
                avgFetchTime: this.performanceMetrics.fetchTimes.reduce((a, b) => a + b, 0) / this.performanceMetrics.fetchTimes.length || 0,
                avgRenderTime: this.performanceMetrics.renderTimes.reduce((a, b) => a + b, 0) / this.performanceMetrics.renderTimes.length || 0,
                cacheHitRate: this.performanceMetrics.cacheHits / (this.performanceMetrics.cacheHits + this.performanceMetrics.cacheMisses) || 0
            },
            state: {
                totalItems: this.allLoadedItems.length,
                displayedItems: this.displayedItems.length,
                errorCount: this.errorCount,
                hasMore: this.hasMoreContent
            }
        };
    }

}

// Enhanced helper functions for image modal integration
function openImageModal(imageUrl, timestamp) {
    if (typeof showModalWithImageAndBbox === 'function') {
        showModalWithImageAndBbox(imageUrl, null, timestamp);
    } else {
        // Fallback to window.open if modal function not available
        window.open(imageUrl, '_blank');
    }
}

/**
 * Advanced image modal function with full item context
 */
function openAdvancedImageModal(imageUrl, bbox, timestamp, itemData) {
    console.log('[UnifiedFeed] Opening advanced image modal:', { imageUrl, bbox, timestamp });
    
    if (typeof showModalWithImageAndBbox === 'function') {
        // Parse bbox if it's a string
        let parsedBbox = bbox;
        if (typeof bbox === 'string') {
            try {
                parsedBbox = JSON.parse(bbox);
            } catch (e) {
                console.warn('[UnifiedFeed] Failed to parse bbox:', e);
                parsedBbox = null;
            }
        }
        
        showModalWithImageAndBbox(imageUrl, parsedBbox, timestamp);
    } else {
        // Enhanced fallback with item details
        console.warn('[UnifiedFeed] showModalWithImageAndBbox not available, using enhanced fallback');
        
        // Create a temporary modal with item details
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Classification Image</h5>
                        <button type="button" class="close" data-dismiss="modal">
                            <span>&times;</span>
                        </button>
                    </div>
                    <div class="modal-body text-center">
                        <img src="${imageUrl}" class="img-fluid" alt="Classification image">
                        <div class="mt-3">
                            <small class="text-muted">Timestamp: ${timestamp}</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <a href="${imageUrl}" target="_blank" class="btn btn-primary">Open in New Tab</a>
                        <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        if (window.$ && $(modal).modal) {
            $(modal).modal('show');
            $(modal).on('hidden.bs.modal', () => {
                document.body.removeChild(modal);
            });
        } else {
            // Even simpler fallback
            window.open(imageUrl, '_blank');
            document.body.removeChild(modal);
        }
    }
}

/**
 * Global function to access feed performance stats (for debugging)
 */
window.getUnifiedFeedStats = function() {
    // Find the feed instance (assuming it's stored globally or can be found)
    if (window.unifiedFeedInstance) {
        return window.unifiedFeedInstance.getPerformanceStats();
    } else {
        console.warn('UnifiedFeed instance not found globally');
        return null;
    }
};

/**
 * Global function to clear feed cache
 */
window.clearUnifiedFeedCache = function() {
    if (window.unifiedFeedInstance) {
        window.unifiedFeedInstance.cache.clear();
        console.log('[UnifiedFeed] Cache cleared manually');
        return true;
    } else {
        console.warn('UnifiedFeed instance not found globally');
        return false;
    }
};