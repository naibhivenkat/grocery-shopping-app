package com.example.groceryshoppingapp.adapters

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.CartItem
import com.squareup.picasso.Picasso

class CartAdapter(
    private val context: Context,
    private val cartItems: MutableList<CartItem>,
    private val onQuantityChanged: () -> Unit
) : RecyclerView.Adapter<CartAdapter.CartViewHolder>() {

    inner class CartViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val nameTextView: TextView = itemView.findViewById(R.id.textViewItemName)
        val quantityEditText: EditText = itemView.findViewById(R.id.editTextQuantity)
        val plusButton: ImageButton = itemView.findViewById(R.id.buttonIncrement)
        val minusButton: ImageButton = itemView.findViewById(R.id.buttonDecrement)
        val priceTextView: TextView = itemView.findViewById(R.id.textViewItemPrice)
        val itemImageView: ImageView = itemView.findViewById(R.id.imageViewItem)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): CartViewHolder {
        val view = LayoutInflater.from(context).inflate(R.layout.item_cart, parent, false)
        return CartViewHolder(view)
    }

    override fun onBindViewHolder(holder: CartViewHolder, position: Int) {
        val item = cartItems[position]
        holder.nameTextView.text = item.item.name
        holder.priceTextView.text = "₹%.2f".format(item.item.price)
        holder.quantityEditText.setText(item.quantity.toString())

        // ✅ Theme-aware text colors
        holder.nameTextView.setTextColor(context.getColorFromAttr(com.google.android.material.R.attr.colorOnBackground))
        holder.priceTextView.setTextColor(context.getColorFromAttr(com.google.android.material.R.attr.colorOnBackground))
        holder.quantityEditText.setTextColor(context.getColorFromAttr(com.google.android.material.R.attr.colorOnBackground))

        // Load image
        if (!item.item.imageUrl.isNullOrEmpty()) {
            Picasso.get().load(item.item.imageUrl).placeholder(R.drawable.placeholder).into(holder.itemImageView)
        } else {
            holder.itemImageView.setImageResource(R.drawable.placeholder)
        }

        // Increment/Decrement buttons
        holder.plusButton.setOnClickListener {
            item.quantity++
            holder.quantityEditText.setText(item.quantity.toString())
            onQuantityChanged()
        }

        holder.minusButton.setOnClickListener {
            if (item.quantity > 1) {
                item.quantity--
                holder.quantityEditText.setText(item.quantity.toString())
                onQuantityChanged()
            } else {
                cartItems.removeAt(position)
                notifyItemRemoved(position)
                notifyItemRangeChanged(position, cartItems.size)
                Toast.makeText(context, "${item.item.name} removed from cart", Toast.LENGTH_SHORT).show()
                onQuantityChanged()
            }
        }

        // Custom numeric keypad
        holder.quantityEditText.setOnClickListener {
            showNumericKeypad(holder.quantityEditText, item, position)
        }
    }

    override fun getItemCount(): Int = cartItems.size

    private fun showNumericKeypad(editText: EditText, cartItem: CartItem, position: Int) {
        val inflater = LayoutInflater.from(editText.context)
        val keypadView = inflater.inflate(R.layout.numeric_keypad, null)

        val popupWindow = PopupWindow(
            keypadView,
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            true
        ).apply {
            elevation = 10f
            isFocusable = true
            isOutsideTouchable = true
            setBackgroundDrawable(android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT))
        }

        var input = ""

        val numberButtons = listOf(
            keypadView.findViewById<Button>(R.id.btn0),
            keypadView.findViewById<Button>(R.id.btn1),
            keypadView.findViewById<Button>(R.id.btn2),
            keypadView.findViewById<Button>(R.id.btn3),
            keypadView.findViewById<Button>(R.id.btn4),
            keypadView.findViewById<Button>(R.id.btn5),
            keypadView.findViewById<Button>(R.id.btn6),
            keypadView.findViewById<Button>(R.id.btn7),
            keypadView.findViewById<Button>(R.id.btn8),
            keypadView.findViewById<Button>(R.id.btn9)
        )

        numberButtons.forEach { btn ->
            // ✅ Theme-aware text
            btn.setTextColor(editText.context.getColorFromAttr(com.google.android.material.R.attr.colorOnBackground))
            btn.setOnClickListener {
                input += btn.text
                editText.setText(input)
                editText.setSelection(input.length)
            }
        }

        keypadView.findViewById<Button>(R.id.btnClear).setOnClickListener {
            if (input.isNotEmpty()) {
                input = input.dropLast(1)
                editText.setText(input)
                editText.setSelection(input.length)
            }
        }

        keypadView.findViewById<Button>(R.id.btnDone).setOnClickListener {
            val newQty = input.toIntOrNull()
            if (newQty != null && newQty > 0) {
                cartItem.quantity = newQty
                notifyItemChanged(position)
                onQuantityChanged()
            } else {
                Toast.makeText(context, "Invalid quantity", Toast.LENGTH_SHORT).show()
            }
            popupWindow.dismiss()
        }

        editText.post {
            popupWindow.showAtLocation(editText, android.view.Gravity.BOTTOM, 0, 0)
        }
    }
}

// Extension function to get theme colors
fun Context.getColorFromAttr(attr: Int): Int {
    val typedArray = obtainStyledAttributes(intArrayOf(attr))
    val color = typedArray.getColor(0, 0)
    typedArray.recycle()
    return color
}
