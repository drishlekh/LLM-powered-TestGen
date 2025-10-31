
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from groq import Groq
from dotenv import load_dotenv
import time
import random
import json
from collections import defaultdict
from agent import run_graph_agent
import markdown 

# --- NEW FIREBASE IMPORTS AND INITIALIZATION ---
import firebase_admin
from firebase_admin import credentials, auth, firestore

load_dotenv()

cred = credentials.Certificate("firebase_admin_sdk.json")
firebase_admin.initialize_app(cred)
db = firestore.client() # This gives us a Firestore client to interact with the database later


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key_here')

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SUBJECTS = ["Logical Reasoning", "Quantitative Aptitude", "Verbal Ability"]
SUBJECT_MAP = {"Logical Reasoning": "LR", "Quantitative Aptitude": "QA", "Verbal Ability": "VA"}

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.user = None
    g.guest_id = session.get('guest_id')

    if user_id:
        try:
            g.user = auth.get_user(user_id)
        except auth.UserNotFoundError:
            session.clear() # User not found in Firebase, clear the session


# NEW version - replace the old @app.route('/') with this
@app.route('/', methods=['GET', 'POST'])
def index():
    # This is the POST request part for starting a quiz
    if request.method == 'POST':
        # This logic only runs when the quiz setup form is submitted
        # Ensure the user is either a guest or logged in before starting
        if not g.user and not g.guest_id:
            return redirect(url_for('login')) # Should not happen, but a good safeguard

        selected_subjects = request.form.getlist('subjects')
        difficulty = request.form.get('difficulty', 'Medium')
        num_questions = min(int(request.form.get('num_questions', 5)), 30)
        timed_test = request.form.get('timed_test') == 'on'
        
        questions = []
        if selected_subjects:
            questions_per_subject = num_questions // len(selected_subjects)
            remaining_questions = num_questions % len(selected_subjects)
            
            for i, subject in enumerate(selected_subjects):
                q_count = questions_per_subject + (1 if i < remaining_questions else 0)
                if q_count > 0:
                    subject_questions = generate_questions(subject, difficulty, q_count)
                    for q in subject_questions:
                        q['subject'] = subject
                        q.setdefault('chapter', 'General')
                    questions.extend(subject_questions)
        
        random.shuffle(questions)
        
        session['questions'] = questions
        session['score'] = 0
        session['start_time'] = time.time()
        session['timed_test'] = timed_test
        session['user_answers'] = {}
        
        return redirect(url_for('quiz'))
    
    # This is the GET request part for showing a page
    # If user is logged in or is a guest, show the quiz setup page (index.html)
    if g.user or g.guest_id:
        return render_template('index.html', subjects=SUBJECTS)
    
    # Otherwise, if no one is logged in, show the new welcome page
    return render_template('welcome.html')

@app.route('/quiz')
def quiz():
    if 'questions' not in session:
        return redirect(url_for('index'))
    
    all_questions = session.get('questions', [])
    
    time_left = None
    if session.get('timed_test'):
        elapsed = time.time() - session['start_time']
        total_time = len(all_questions) * 60
        time_left = max(0, total_time - elapsed)

    return render_template('quiz.html', 
                           questions=all_questions,
                           total_questions=len(all_questions),
                           timed_test=session.get('timed_test', False),
                           time_left=time_left,
                           subject_map=SUBJECT_MAP)


@app.route('/check_answer', methods=['POST'])
def check_answer():
    if 'questions' not in session:
        return jsonify({'error': 'Session expired'}), 400
    
    data = request.get_json()
    selected_option = data.get('selected_option')
    question_index = data.get('question_index')

    all_questions = session.get('questions', [])
    
    if question_index is None or not (0 <= question_index < len(all_questions)):
        return jsonify({'error': 'Invalid question index'}), 400
        
    question = all_questions[question_index]
    is_correct = (selected_option == question['correct_answer'])
    
    session['user_answers'][str(question_index)] = {
        'user_answer': selected_option,
        'is_correct': is_correct
    }
    
    session.modified = True
    
    return jsonify({
        'is_correct': is_correct,
        'correct_answer': question['correct_answer'],
        'solution': question.get('solution', "Solution not available.")
    })



# NEWEST version - replace the @app.route('/results') function with this
@app.route('/results')
def results():
    if 'questions' not in session:
        return redirect(url_for('index'))

    all_questions = session.get('questions', [])
    user_answers = session.get('user_answers', {})
    
    score = 0
    correct_count = 0
    incorrect_count = 0
    
    topic_breakdown = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'total': 0})

    for i, q in enumerate(all_questions):
        subject_abbr = SUBJECT_MAP.get(q.get('subject'), 'Unknown')
        topic = f"{subject_abbr} -> {q.get('chapter', 'General')}"
        topic_breakdown[topic]['total'] += 1
        
        answer_info = user_answers.get(str(i))
        if answer_info:
            if answer_info['is_correct']:
                correct_count += 1
                topic_breakdown[topic]['correct'] += 1
            else:
                incorrect_count += 1
                topic_breakdown[topic]['incorrect'] += 1

    score = correct_count
    total = len(all_questions)
    accuracy = (score / total * 100) if total > 0 else 0
    total_time_taken = time.time() - session.get('start_time', 0)

    student_name = g.user.email if g.user else "Guest"

    report_data = {
        'student_name': student_name,
        'score': score,
        'total_questions': total,
        'accuracy': round(accuracy, 2),
        'correct_count': correct_count,
        'incorrect_count': incorrect_count,
        'unanswered_count': total - (correct_count + incorrect_count),
        'total_time_taken': round(total_time_taken),
        'topic_breakdown': {k: dict(v) for k, v in topic_breakdown.items()}
    }

    if g.user:
        try:
            data_to_save = report_data.copy()
            data_to_save['timestamp'] = firestore.SERVER_TIMESTAMP

            # --- THIS IS THE KEY CHANGE ---
            # Old way: db.collection('quiz_results').add(...)
            # New way: Create a document for the user in the 'users' collection,
            # and then add the quiz result to a 'quiz_results' subcollection within that user's document.
            user_doc_ref = db.collection('users').document(g.user.uid)
            user_doc_ref.collection('quiz_results').add(data_to_save)
            
            # We can also set some basic user info on the main user document
            user_doc_ref.set({'email': g.user.email}, merge=True)
            
            print(f"Successfully saved quiz results for user: {g.user.uid}")

        except Exception as e:
            print(f"Error saving to Firestore: {e}")

    session.pop('questions', None)
    session.pop('user_answers', None)
    session.pop('start_time', None)
    session.pop('timed_test', None)

    return render_template('results.html', 
                         score=score, 
                         total=total,
                         report_data_json=json.dumps(report_data))
    
    
    
    
@app.route('/report', methods=['POST'])
def report_page():
    report_data_str = request.form.get('report_data')
    if not report_data_str:
        return "Error: No report data found.", 400
        
    report_data = json.loads(report_data_str)

    # Call our agent to get the report as a Markdown string
    agent_response = run_graph_agent(report_data)
    
    # Convert the Markdown string from the agent into HTML
    report_html = markdown.markdown(agent_response.get("analysis", ""))
    
    # Pass the generated HTML to the template
    return render_template('report.html', 
                           report_data=report_data, 
                           report_html=report_html) # Pass HTML, not text

def generate_questions(subject, difficulty, num_questions):
    subject_instructions = {
        "Logical Reasoning": "Chapters may include: Syllogisms, Blood Relations, Coding-Decoding, Seating Arrangement, Direction Sense.",
        "Quantitative Aptitude": "Chapters may include: Time & Work, Percentages, Profit & Loss, Speed Time & Distance, Ratios.",
        "Verbal Ability": "Chapters may include: Synonyms & Antonyms, Reading Comprehension, Sentence Correction, Para Jumbles, Idioms & Phrases."
    }
    prompt = f"""
    Generate exactly {num_questions} multiple choice questions (MCQ) about {subject} with {difficulty.lower()} difficulty,
    focused on engineering placement scenarios in Indian B.Tech colleges like those asked by companies like Infosys, Wipro, TCS.
    {subject_instructions.get(subject, '')}

    For each question, provide:
    1. The question text.
    2. A specific chapter or topic name for the question (e.g., "Time & Work", "Syllogisms").
    3. Four options labeled A), B), C), D).
    4. The correct answer letter.
    5. A detailed step-by-step solution.

    Format EACH question as a JSON object like this:
    {{
        "chapter": "Chapter Name Here",
        "question": "Question text here",
        "options": {{ "A": "option 1", "B": "option 2", "C": "option 3", "D": "option 4" }},
        "correct_answer": "Correct letter here",
        "solution": "Detailed step-by-step solution here"
    }}

    Return ONLY a JSON array of these questions with the key "questions". Do not include any other text or explanations.
    """
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.7
        )
        response = chat_completion.choices[0].message.content
        questions = json.loads(response).get('questions', [])
        
        if len(questions) < num_questions:
            needed = num_questions - len(questions)
            questions.extend(get_default_questions(subject, needed))
            
        return questions[:num_questions]
    
    except Exception as e:
        return get_default_questions(subject, num_questions)

def get_default_questions(subject, num_questions):
    defaults = {
        "Logical Reasoning": [{"chapter": "Syllogisms", "question": "If all Bloops are Razzies and all Razzies are Lazzies, then all Bloops are definitely Lazzies?", "options": {"A": "True", "B": "False", "C": "Uncertain", "D": "None of the above"}, "correct_answer": "A", "solution": "This is a case of transitive relation. If A implies B and B implies C, then A implies C. So, the statement is True."}],
        "Quantitative Aptitude": [{"chapter": "Speed, Time & Distance", "question": "If a train travels 300 km in 5 hours, what is its average speed?", "options": {"A": "50 km/h", "B": "60 km/h", "C": "70 km/h", "D": "80 km/h"}, "correct_answer": "B", "solution": "Average Speed = Total Distance / Total Time. Speed = 300 km / 5 hours = 60 km/h."}],
        "Verbal Ability": [{"chapter": "Synonyms", "question": "Choose the correct synonym for 'Benevolent'", "options": {"A": "Cruel", "B": "Kind", "C": "Selfish", "D": "Greedy"}, "correct_answer": "B", "solution": "'Benevolent' means well-meaning and kindly. 'Kind' is the closest synonym."}]
    }
    subject_questions = defaults.get(subject, [])
    return subject_questions[:num_questions]



# ADD THIS NEW ROUTE
@app.route('/auth')
def auth_page():
    return render_template('auth.html')



# ... after the get_default_questions function ...

# @app.route('/signup', methods=['GET', 'POST'])
# def signup():
#     if request.method == 'POST':
#         email = request.form.get('email')
#         password = request.form.get('password')
#         try:
#             user = auth.create_user(
#                 email=email,
#                 password=password
#             )
#             session['user_id'] = user.uid # Log the user in immediately
#             return redirect(url_for('index'))
#         except Exception as e:
#             # Handle errors, e.g., email already exists
#             return render_template('signup.html', error=f"Error: {e}")
#     return render_template('signup.html')
# REPLACE the old /signup route with this
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Get the role from the hidden input, default to 'student' if not provided
        role = request.form.get('role', 'student') 
        
        try:
            # Step 1: Create the user in Firebase Authentication
            user = auth.create_user(
                email=email,
                password=password
            )

            # Step 2: Create a user document in Firestore with their role
            user_doc_ref = db.collection('users').document(user.uid)
            user_doc_ref.set({
                'email': user.email,
                'role': role  # Use the role from the form
            })
            
            # Step 3: Log the user in and redirect
            session['user_id'] = user.uid
            return redirect(url_for('index'))

        except Exception as e:
            # For a better user experience, we redirect back to the auth page with an error
            # We will need to add logic to auth.html to display this error.
            # For now, this is a simple error handling.
            print(f"Signup Error: {e}")
            return redirect(url_for('auth_page')) # Redirect back to the main auth page

    # If it's a GET request, just show the auth page.
    return redirect(url_for('auth_page'))

# REPLACE the old /login route with this
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        # We are not verifying password on the backend in this simplified flow.
        # A production app should use a more secure method.
        try:
            # Step 1: Get the user from Firebase Auth
            user = auth.get_user_by_email(email)

            # Step 2: Get the user's document from Firestore to check their role
            user_doc_ref = db.collection('users').document(user.uid)
            user_doc = user_doc_ref.get()

            if not user_doc.exists:
                # This case handles users who might exist in Auth but not Firestore
                print("User exists in Auth, but not in Firestore.")
                return redirect(url_for('auth_page'))

            user_role = user_doc.to_dict().get('role')

            # Step 3: Log the user in by setting the session
            session['user_id'] = user.uid

            # Step 4: Redirect based on role
            if user_role == 'teacher':
                return redirect(url_for('teacher_dashboard')) # A new route we will create next
            else: # 'student'
                return redirect(url_for('index'))

        except Exception as e:
            print(f"Login Error: {e}")
            return redirect(url_for('auth_page'))

    # If it's a GET request, just show the auth page.
    return redirect(url_for('auth_page'))

@app.route('/logout')
def logout():
    session.clear() # Clears the entire session, logging out users and guests
    return redirect(url_for('index'))

@app.route('/continue_as_guest', methods=['POST'])
def continue_as_guest():
    session.clear() # Clear any old session
    session['guest_id'] = f"guest_{int(time.time())}" # Create a unique guest ID
    return redirect(url_for('index'))

# We will add the /user_history route in a later step
# NEW functional version - replace the old @app.route('/user_history')
# REPLACE the existing /user_history route with this new version
@app.route('/user_history')
def user_history():
    if not g.user:
        return redirect(url_for('login'))

    results_list = []
    try:
        # Query Firestore, ordering by timestamp ASCENDING so the graph goes from oldest to newest
        docs = db.collection('users').document(g.user.uid).collection('quiz_results').order_by(
            'timestamp', direction=firestore.Query.ASCENDING
        ).stream()

        for doc in docs:
            result_data = doc.to_dict()
            
            # Format the timestamp for display in the list on the left
            if 'timestamp' in result_data and result_data['timestamp']:
                timestamp = result_data['timestamp']
                # Store the original Python datetime object for JS to parse easily
                result_data['timestamp_raw'] = timestamp.isoformat()
                result_data['timestamp'] = timestamp.strftime("%B %d, %Y - %I:%M %p")
            else:
                result_data['timestamp_raw'] = None
                result_data['timestamp'] = "No date available"

            results_list.append(result_data)

    except Exception as e:
        print(f"Error fetching user history: {e}")

    # Pass the results twice: once for the Jinja loop, once as JSON for the JavaScript chart
    return render_template('history.html', 
                           results=results_list, 
                           results_json=json.dumps(results_list, default=str))

# REPLACE the old /teacher_dashboard placeholder with this
@app.route('/teacher_dashboard')
def teacher_dashboard():
    # Security Check 1: Ensure a user is logged in.
    if not g.user:
        return redirect(url_for('auth_page'))
    
    # Security Check 2: Ensure the user's role is 'teacher'.
    user_doc = db.collection('users').document(g.user.uid).get()
    if not user_doc.exists or user_doc.to_dict().get('role') != 'teacher':
        # If they are not a teacher, send them to the student homepage.
        return redirect(url_for('index'))

    # If security checks pass, proceed to fetch student data.
    students_list = []
    try:
        # Query the 'users' collection for all documents where the 'role' field is 'student'
        docs = db.collection('users').where('role', '==', 'student').stream()
        for doc in docs:
            student_data = doc.to_dict()
            student_data['id'] = doc.id  # Add the document ID (user's UID) to the dictionary
            students_list.append(student_data)
    except Exception as e:
        print(f"Error fetching students: {e}")

    return render_template('teacher_dashboard.html', students=students_list)



# REPLACE the existing /student_history/<student_id> route with this FINAL version
@app.route('/student_history/<student_id>')
def view_student_history(student_id):
    # Security Check: Ensure the person viewing is a teacher
    if not g.user:
        return redirect(url_for('auth_page'))
    user_doc_check = db.collection('users').document(g.user.uid).get()
    if not user_doc_check.exists or user_doc_check.to_dict().get('role') != 'teacher':
        return redirect(url_for('index'))

    results_list = []
    student_email = "Student not found"
    try:
        student_doc = db.collection('users').document(student_id).get()
        if student_doc.exists:
            student_email = student_doc.to_dict().get('email', 'N/A')

        # CRITICAL FIX 1: Order by ASCENDING for a correct timeline graph
        docs = db.collection('users').document(student_id).collection('quiz_results').order_by(
            'timestamp', direction=firestore.Query.ASCENDING
        ).stream()

        for doc in docs:
            result_data = doc.to_dict()
            result_data['id'] = doc.id # Needed for the modal button

            if 'timestamp' in result_data and result_data['timestamp']:
                timestamp = result_data['timestamp']
                # CRITICAL FIX 2: Create a universal ISO format for JavaScript
                result_data['timestamp_raw'] = timestamp.isoformat()
                # Create the pretty format for the list display
                result_data['timestamp'] = timestamp.strftime("%B %d, %Y at %I:%M %p")
            else:
                result_data['timestamp_raw'] = None
                result_data['timestamp'] = "No date available"
            
            results_list.append(result_data)

    except Exception as e:
        print(f"Error fetching student history: {e}")

    return render_template('view_student_history.html', 
                           results=results_list, 
                           student_email=student_email,
                           student_id=student_id,
                           results_json=json.dumps(results_list, default=str))
    
# ADD THIS FINAL ROUTE
@app.route('/get_report/<student_id>/<result_id>')
def get_report(student_id, result_id):
    # Security Check: Ensure the person viewing is a teacher
    if not g.user or not db.collection('users').document(g.user.uid).get().to_dict().get('role') == 'teacher':
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Fetch the specific quiz result document from Firestore
        doc_ref = db.collection('users').document(student_id).collection('quiz_results').document(result_id)
        result_doc = doc_ref.get()

        if not result_doc.exists:
            return jsonify({"error": "Report not found"}), 404

        # The document data is the 'report_data' our agent needs
        report_data = result_doc.to_dict()

        # --- Call our AI agent to generate the analysis ---
        agent_response = run_graph_agent(report_data)
        
        # Convert the Markdown string from the agent into HTML
        report_html = markdown.markdown(agent_response.get("analysis", "Error: Could not generate report."))
        
        return jsonify({"html": report_html})

    except Exception as e:
        print(f"Error getting report: {e}")
        return jsonify({"error": "An internal error occurred."}), 500    

if __name__ == '__main__':
    app.run(debug=True)







# import os
# from flask import Flask, render_template, request, jsonify, session, redirect, url_for
# from groq import Groq
# from dotenv import load_dotenv
# import time
# import random
# import json
# from collections import defaultdict

# # --- We will import agent.py here later ---
# from agent import run_graph_agent
# import markdown

# load_dotenv()

# app = Flask(__name__)
# app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key_here')

# client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# SUBJECTS = ["Logical Reasoning", "Quantitative Aptitude", "Verbal Ability"]
# SUBJECT_MAP = {
#     "Logical Reasoning": "LR",
#     "Quantitative Aptitude": "QA",
#     "Verbal Ability": "VA"
# }

# @app.route('/', methods=['GET', 'POST'])
# def index():
#     if request.method == 'POST':
#         selected_subjects = request.form.getlist('subjects')
#         difficulty = request.form.get('difficulty', 'Medium')
#         num_questions = min(int(request.form.get('num_questions', 5)), 30)
#         timed_test = request.form.get('timed_test') == 'on'
        
#         questions = []
#         if selected_subjects:
#             questions_per_subject = num_questions // len(selected_subjects)
#             remaining_questions = num_questions % len(selected_subjects)
            
#             for i, subject in enumerate(selected_subjects):
#                 q_count = questions_per_subject + (1 if i < remaining_questions else 0)
#                 if q_count > 0:
#                     subject_questions = generate_questions(subject, difficulty, q_count)
#                     for q_idx, q in enumerate(subject_questions):
#                         q['subject'] = subject
#                         q['id'] = f"{subject}-{i}-{q_idx}" # Unique ID for each question
#                         q.setdefault('chapter', 'General')
#                     questions.extend(subject_questions)
        
#         random.shuffle(questions)
        
#         session['questions'] = questions
#         session['score'] = 0
#         session['start_time'] = time.time()
#         session['timed_test'] = timed_test
        
#         # This will now store the full question object after it's answered
#         session['user_answers'] = {} 
        
#         return redirect(url_for('quiz'))
    
#     return render_template('index.html', subjects=SUBJECTS)

# @app.route('/quiz')
# def quiz():
#     if 'questions' not in session:
#         return redirect(url_for('index'))
    
#     all_questions = session.get('questions', [])
    
#     time_left = None
#     if session.get('timed_test'):
#         elapsed = time.time() - session['start_time']
#         total_time = len(all_questions) * 60 # 60 seconds per question
#         time_left = max(0, total_time - elapsed)

#     # CORRECTION: Pass the Python list/dict directly.
#     # The 'tojson' filter in the template will handle the conversion safely.
#     return render_template('quiz.html', 
#                            questions=all_questions, # Pass the python object
#                            total_questions=len(all_questions),
#                            timed_test=session.get('timed_test', False),
#                            time_left=time_left,
#                            subject_map=SUBJECT_MAP) # Pass the python object


# @app.route('/check_answer', methods=['POST'])
# def check_answer():
#     if 'questions' not in session:
#         return jsonify({'error': 'Session expired'}), 400
    
#     data = request.get_json()
#     selected_option = data.get('selected_option')
#     question_index = data.get('question_index')

#     all_questions = session.get('questions', [])
    
#     if question_index is None or not (0 <= question_index < len(all_questions)):
#         return jsonify({'error': 'Invalid question index'}), 400
        
#     question = all_questions[question_index]
#     is_correct = (selected_option == question['correct_answer'])
    
#     # Store the user's response in the session
#     session['user_answers'][str(question_index)] = {
#         'user_answer': selected_option,
#         'is_correct': is_correct
#     }
    
#     session.modified = True
    
#     return jsonify({
#         'is_correct': is_correct,
#         'correct_answer': question['correct_answer'],
#         'solution': question.get('solution', "Solution not available.")
#     })


# @app.route('/results')
# def results():
#     if 'questions' not in session:
#         return redirect(url_for('index'))

#     all_questions = session.get('questions', [])
#     user_answers = session.get('user_answers', {})
    
#     score = 0
#     correct_count = 0
#     incorrect_count = 0
    
#     topic_breakdown = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'total': 0})

#     for i, q in enumerate(all_questions):
#         subject_abbr = SUBJECT_MAP.get(q.get('subject'), 'Unknown')
#         topic = f"{subject_abbr} -> {q.get('chapter', 'General')}"
#         topic_breakdown[topic]['total'] += 1
        
#         answer_info = user_answers.get(str(i))
#         if answer_info:
#             if answer_info['is_correct']:
#                 correct_count += 1
#                 topic_breakdown[topic]['correct'] += 1
#             else:
#                 incorrect_count += 1
#                 topic_breakdown[topic]['incorrect'] += 1

#     score = correct_count
#     total = len(all_questions)
#     accuracy = (score / total * 100) if total > 0 else 0
#     total_time_taken = time.time() - session.get('start_time', 0)

#     report_data = {
#         'student_name': 'User',
#         'score': score,
#         'total_questions': total,
#         'accuracy': round(accuracy, 2),
#         'correct_count': correct_count,
#         'incorrect_count': incorrect_count,
#         'unanswered_count': total - (correct_count + incorrect_count),
#         'total_time_taken': round(total_time_taken),
#         'topic_breakdown': dict(topic_breakdown)
#     }

#     session.clear()

#     return render_template('results.html', 
#                          score=score, 
#                          total=total,
#                          report_data_json=json.dumps(report_data))


# @app.route('/report', methods=['POST'])
# def report_page():
#     report_data_str = request.form.get('report_data')
#     if not report_data_str:
#         return "Error: No report data found.", 400
        
#     report_data = json.loads(report_data_str)

#     # This is the magic moment! We call our agent with the data.
#     agent_response = run_graph_agent(report_data)
    
#     # Convert the Markdown response from the agent into HTML
#     report_html = markdown.markdown(agent_response.get("analysis", ""))
    
#     return render_template('report.html', 
#                            report_data=report_data, 
#                            report_html=report_html)

# # --- The generate_questions and get_default_questions functions remain unchanged ---
# def generate_questions(subject, difficulty, num_questions):
#     # (This function is the same as in the previous step, no changes needed)
#     subject_instructions = {
#         "Logical Reasoning": "Chapters may include: Syllogisms, Blood Relations, Coding-Decoding, Seating Arrangement, Direction Sense.",
#         "Quantitative Aptitude": "Chapters may include: Time & Work, Percentages, Profit & Loss, Speed Time & Distance, Ratios.",
#         "Verbal Ability": "Chapters may include: Synonyms & Antonyms, Reading Comprehension, Sentence Correction, Para Jumbles, Idioms & Phrases."
#     }
#     prompt = f"""
#     Generate exactly {num_questions} multiple choice questions (MCQ) about {subject} with {difficulty.lower()} difficulty,
#     focused on engineering placement scenarios in Indian B.Tech colleges like those asked by companies like Infosys, Wipro, TCS.
#     {subject_instructions.get(subject, '')}

#     For each question, provide:
#     1. The question text.
#     2. A specific chapter or topic name for the question (e.g., "Time & Work", "Syllogisms").
#     3. Four options labeled A), B), C), D).
#     4. The correct answer letter.
#     5. A detailed step-by-step solution.

#     Format EACH question as a JSON object like this:
#     {{
#         "chapter": "Chapter Name Here",
#         "question": "Question text here",
#         "options": {{ "A": "option 1", "B": "option 2", "C": "option 3", "D": "option 4" }},
#         "correct_answer": "Correct letter here",
#         "solution": "Detailed step-by-step solution here"
#     }}

#     Return ONLY a JSON array of these questions with the key "questions". Do not include any other text or explanations.
#     """
#     try:
#         chat_completion = client.chat.completions.create(
#             messages=[{"role": "user", "content": prompt}],
#             model="llama3-8b-8192",
#             response_format={"type": "json_object"},
#             temperature=0.7
#         )
#         response = chat_completion.choices[0].message.content
#         questions = json.loads(response).get('questions', [])
        
#         if len(questions) < num_questions:
#             needed = num_questions - len(questions)
#             questions.extend(get_default_questions(subject, needed))
            
#         return questions[:num_questions]
    
#     except Exception as e:
#         return get_default_questions(subject, num_questions)

# def get_default_questions(subject, num_questions):
#     # (This function is the same as in the previous step, no changes needed)
#     defaults = {
#         "Logical Reasoning": [{"chapter": "Syllogisms", "question": "If all Bloops are Razzies and all Razzies are Lazzies, then all Bloops are definitely Lazzies?", "options": {"A": "True", "B": "False", "C": "Uncertain", "D": "None of the above"}, "correct_answer": "A", "solution": "This is a case of transitive relation. If A implies B and B implies C, then A implies C. So, the statement is True."}],
#         "Quantitative Aptitude": [{"chapter": "Speed, Time & Distance", "question": "If a train travels 300 km in 5 hours, what is its average speed?", "options": {"A": "50 km/h", "B": "60 km/h", "C": "70 km/h", "D": "80 km/h"}, "correct_answer": "B", "solution": "Average Speed = Total Distance / Total Time. Speed = 300 km / 5 hours = 60 km/h."}],
#         "Verbal Ability": [{"chapter": "Synonyms", "question": "Choose the correct synonym for 'Benevolent'", "options": {"A": "Cruel", "B": "Kind", "C": "Selfish", "D": "Greedy"}, "correct_answer": "B", "solution": "'Benevolent' means well-meaning and kindly. 'Kind' is the closest synonym."}]
#     }
#     subject_questions = defaults.get(subject, [])
#     return subject_questions[:num_questions]


# if __name__ == '__main__':
#     app.run(debug=True)

