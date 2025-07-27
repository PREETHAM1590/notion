const express = require('express');
const fs = require('fs');
const path = require('path');
const bodyParser = require('body-parser');
const cookieParser = require('cookie-parser');
const { v4: uuidv4 } = require('crypto');

const app = express();
const PORT = 8000;

// Middleware
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(cookieParser());
app.use('/static', express.static(path.join(__dirname, 'static')));
app.engine('html', require('ejs').renderFile);
app.set('view engine', 'html');
app.set('views', path.join(__dirname, 'templates'));

// Data files
const DATA_FILE = path.join(__dirname, 'pages.json');
const SETTINGS_FILE = path.join(__dirname, 'settings.json');

// In-memory stores
let DATA = {};
let SETTINGS = {};
let SESSIONS = {};
let CHAT_HISTORY = [];

// Load data functions
function loadData() {
    try {
        if (fs.existsSync(DATA_FILE)) {
            const data = fs.readFileSync(DATA_FILE, 'utf8');
            return JSON.parse(data);
        }
    } catch (error) {
        console.log('Error loading data, starting fresh');
    }
    
    // Initialize with default data
    const rootId = generateUUID();
    const defaultData = {
        [rootId]: {
            title: "Home",
            content: "Welcome to your Notion-style workspace!",
            children: [],
            database: []
        }
    };
    saveData(defaultData);
    return defaultData;
}

function saveData(data) {
    try {
        fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
    } catch (error) {
        console.error('Error saving data:', error);
    }
}

function loadSettings() {
    try {
        if (fs.existsSync(SETTINGS_FILE)) {
            const settings = fs.readFileSync(SETTINGS_FILE, 'utf8');
            return JSON.parse(settings);
        }
    } catch (error) {
        console.log('Error loading settings, using defaults');
    }
    return { model: "Gemini", theme: "light" };
}

function saveSettings(settings) {
    try {
        fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
    } catch (error) {
        console.error('Error saving settings:', error);
    }
}

// UUID generator (simplified)
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Initialize data
DATA = loadData();
SETTINGS = loadSettings();

// Helper functions
function getPageTree() {
    function buildNode(pid) {
        const node = {
            id: pid,
            title: DATA[pid].title,
            children: []
        };
        for (const cid of DATA[pid].children) {
            if (DATA[cid]) {
                node.children.push(buildNode(cid));
            }
        }
        return node;
    }

    const allChildren = new Set();
    Object.values(DATA).forEach(page => {
        page.children.forEach(child => allChildren.add(child));
    });

    const rootIds = Object.keys(DATA).filter(id => !allChildren.has(id));
    return rootIds.map(id => buildNode(id));
}

function renderContent(raw) {
    if (!raw) return '';
    
    const lines = raw.split('\n');
    const htmlParts = [];
    let inCode = false;

    for (const line of lines) {
        if (line.trim().startsWith('```')) {
            inCode = !inCode;
            if (inCode) {
                htmlParts.push('<pre><code>');
            } else {
                htmlParts.push('</code></pre>');
            }
            continue;
        }

        if (inCode) {
            htmlParts.push(escapeHtml(line) + '\n');
            continue;
        }

        // Check for checklist items
        const unchecked = line.match(/^- \[ \] (.*)/);
        const checked = line.match(/^- \[x\] (.*)/i);

        if (unchecked) {
            htmlParts.push(`<label><input type="checkbox" disabled> ${escapeHtml(unchecked[1])}</label><br>`);
        } else if (checked) {
            htmlParts.push(`<label><input type="checkbox" checked disabled> ${escapeHtml(checked[1])}</label><br>`);
        } else {
            htmlParts.push(`<p>${escapeHtml(line)}</p>`);
        }
    }

    return htmlParts.join('\n');
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function getCurrentUser(req) {
    const sessionId = req.cookies.session_id;
    return sessionId && SESSIONS[sessionId] ? SESSIONS[sessionId] : null;
}

function requireLogin(req, res, next) {
    const user = getCurrentUser(req);
    if (!user) {
        return res.redirect(`/login?next=${encodeURIComponent(req.path)}`);
    }
    next();
}

// Routes
app.get('/', (req, res) => {
    const pageTree = getPageTree();
    const user = getCurrentUser(req);
    res.render('index', {
        page_tree: pageTree,
        user: user,
        theme: SETTINGS.theme || 'light'
    });
});

app.get('/page/:pageId', (req, res) => {
    const pageId = req.params.pageId;
    if (!DATA[pageId]) {
        return res.redirect('/');
    }

    const page = DATA[pageId];
    const rendered = renderContent(page.content);
    const pageTree = getPageTree();
    const user = getCurrentUser(req);

    res.render('page', {
        page_tree: pageTree,
        page_id: pageId,
        page: page,
        rendered: rendered,
        user: user,
        theme: SETTINGS.theme || 'light'
    });
});

app.get('/page/new', (req, res) => {
    const user = getCurrentUser(req);
    if (!user) {
        return res.redirect(`/login?next=${encodeURIComponent(req.path)}`);
    }

    const pageTree = getPageTree();
    const parent = req.query.parent;

    res.render('new_page', {
        page_tree: pageTree,
        parent: parent,
        user: user,
        theme: SETTINGS.theme || 'light'
    });
});

app.post('/page/new', (req, res) => {
    const user = getCurrentUser(req);
    if (!user) {
        return res.redirect(`/login?next=${encodeURIComponent(req.path)}`);
    }

    const { title, parent } = req.body;
    const pageId = generateUUID();
    
    DATA[pageId] = {
        title: title.trim() || 'Untitled',
        content: '',
        children: [],
        database: []
    };

    if (parent && DATA[parent]) {
        DATA[parent].children.push(pageId);
    }

    saveData(DATA);
    res.redirect(`/page/${pageId}`);
});

app.get('/login', (req, res) => {
    const pageTree = getPageTree();
    const user = getCurrentUser(req);
    const message = req.query.signup === 'success' ? 'Account created successfully. Please log in.' : null;
    const next = req.query.next || '/';

    res.render('login', {
        page_tree: pageTree,
        user: user,
        message: message,
        error: null,
        next: next,
        theme: SETTINGS.theme || 'light'
    });
});

app.post('/login', (req, res) => {
    const { email, password, next } = req.body;
    const nextPath = next || '/';

    // Simple authentication (in production, use proper authentication)
    if (email && password) {
        const sessionId = generateUUID();
        SESSIONS[sessionId] = {
            email: email,
            access_token: 'dummy_token',
            refresh_token: 'dummy_refresh'
        };

        res.cookie('session_id', sessionId, { httpOnly: true });
        return res.redirect(nextPath);
    }

    const pageTree = getPageTree();
    res.render('login', {
        page_tree: pageTree,
        user: null,
        message: null,
        error: 'Invalid credentials',
        next: nextPath,
        theme: SETTINGS.theme || 'light'
    });
});

app.get('/logout', (req, res) => {
    const sessionId = req.cookies.session_id;
    if (sessionId && SESSIONS[sessionId]) {
        delete SESSIONS[sessionId];
    }
    res.clearCookie('session_id');
    res.redirect('/login');
});

// Start server
app.listen(PORT, '127.0.0.1', () => {
    console.log(`Server running at http://127.0.0.1:${PORT}`);
});