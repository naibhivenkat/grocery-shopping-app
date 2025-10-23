package com.example.groceryshoppingapp.adapters

import android.app.Activity
import android.content.Context
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.CartItem

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
        // ✅ FIXED: match your XML ID
        val itemImage: ImageView = itemView.findViewById(R.id.imageViewItem)
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

        // ✅ Fixed image loading with correct placeholder reference
        val imageUrl = item.item.imageUrl?.trim()
        if (!imageUrl.isNullOrEmpty()) {
            val imageToLoad = when {
                imageUrl.startsWith("http", true) -> imageUrl
                imageUrl.startsWith("images/", true) -> "file:///android_asset/$imageUrl"
                imageUrl.startsWith("/images/", true) -> "file:///android_asset$imageUrl"
                else -> null
            }

            Glide.with(holder.itemView.context)
                .load(imageToLoad ?: R.drawable.image_placeholder)
                .placeholder(R.drawable.image_placeholder)
                .error(R.drawable.image_placeholder)
                .centerCrop()
                .into(holder.itemImage)
        } else {
            holder.itemImage.setImageResource(R.drawable.image_placeholder)
        }

        // Increment / Decrement
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

        holder.quantityEditText.setOnClickListener {
            if (context is Activity && !context.isFinishing) {
                showNumericKeypad(holder.quantityEditText, item, position)
            }
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
            val newQty = input.toDoubleOrNull()
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
            popupWindow.showAtLocation(editText, Gravity.BOTTOM, 0, 0)
        }
    }
}
